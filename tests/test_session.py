"""保存済みログインセッションまわりのテスト"""
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import session  # noqa: E402
from engine.site_config import (  # noqa: E402
    SiteConfigError,
    load_site_configs,
    parse_site_config,
)

REPO = Path(__file__).resolve().parents[1]

MANUAL_YAML = {
    "name": "テストサイト",
    "login": {"mode": "manual", "url": "https://example.com/login",
              "success_check": {"url_not_contains": "id.example.com"}},
    "listings": [{"url": "https://example.com/mypage"}],
}


def test_save_and_load_roundtrip(tmp_path):
    state = {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}
    path = session.save(str(tmp_path), "demo", state)

    assert session.exists(str(tmp_path), "demo")
    assert session.load_path(str(tmp_path), "demo") == path
    assert Path(path).read_text(encoding="utf-8").find("sid") != -1
    assert session.age_days(str(tmp_path), "demo") < 1


def test_missing_session_reports_absent(tmp_path):
    assert session.exists(str(tmp_path), "nope") is False
    assert session.load_path(str(tmp_path), "nope") is None
    assert session.age_days(str(tmp_path), "nope") is None
    assert session.is_stale(str(tmp_path), "nope") is True
    assert session.describe(str(tmp_path), "nope") == "未保存"


def test_stale_detection(tmp_path):
    import os
    session.save(str(tmp_path), "old", {"cookies": []})
    path = session.session_path(str(tmp_path), "old")
    old = time.time() - 40 * 86400
    os.utime(path, (old, old))
    assert session.is_stale(str(tmp_path), "old") is True
    assert session.is_stale(str(tmp_path), "old", max_age_days=90) is False


def test_session_dir_is_gitignored():
    """Cookie が入るので、絶対にコミットされてはいけない"""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".sessions/" in ignored


def test_manual_login_mode_parsed():
    site = parse_site_config(MANUAL_YAML, slug="demo")
    assert site.login_mode == "manual"
    assert site.uses_saved_session() is True
    # manual は認証情報を必要としない
    assert site.credentials() == {}
    # steps が無くてもログインが必要なサイトとして扱われる
    assert site.requires_login() is True


def test_steps_mode_is_still_the_default():
    raw = {
        "name": "従来サイト",
        "credentials": {"email_env": "X_EMAIL", "password_env": "X_PASSWORD"},
        "login": {"url": "https://example.com/login",
                  "steps": [{"action": "fill", "selector": "#a", "value": "{email}"}]},
        "listings": [{"url": "https://example.com/jobs"}],
    }
    site = parse_site_config(raw, slug="legacy")
    assert site.login_mode == "steps"
    assert site.uses_saved_session() is False


def test_unknown_login_mode_is_rejected():
    raw = dict(MANUAL_YAML, login=dict(MANUAL_YAML["login"], mode="magic"))
    with pytest.raises(SiteConfigError, match="login.mode"):
        parse_site_config(raw, slug="demo")


@pytest.mark.parametrize("slug", ["mynavi", "rikunabi"])
def test_new_sites_are_manual_and_disabled(slug):
    """未調整の定義が、うっかり有効なまま配布されていないこと"""
    raw = yaml.safe_load((REPO / "sites" / f"{slug}.yaml").read_text(encoding="utf-8"))
    site = parse_site_config(raw, slug=slug)
    assert site.enabled is False, f"{slug}: 一覧ページの調整前に enabled: true になっている"
    assert site.uses_saved_session() is True
    assert site.listings, f"{slug}: listings が空"


def test_all_site_configs_still_load():
    sites = {s.slug for s in load_site_configs(REPO / "sites")}
    assert {"mynavi", "rikunabi"} <= sites


# --------------------------------------------------------------------------
# セッション切れの検出（ブラウザ無しで、偽の Page を渡して確かめる）
# --------------------------------------------------------------------------

class FakePage:
    def __init__(self, url="", body="", selectors=()):
        self.url = url
        self._body = body
        self._selectors = set(selectors)

    async def query_selector(self, selector):
        return object() if selector in self._selectors else None

    async def inner_text(self, _selector):
        return self._body


def _reason(site_raw, page):
    """GenericScraper._logged_out_reason を Playwright 無しで呼ぶ"""
    import asyncio
    import types

    scraper = types.SimpleNamespace(
        site=parse_site_config(site_raw, slug="demo"),
        page=page,
    )
    from engine.scraper import GenericScraper
    return asyncio.run(GenericScraper._logged_out_reason(scraper))


def test_logged_in_when_nothing_matches():
    page = FakePage(url="https://example.com/mypage", body="ようこそ")
    assert _reason(MANUAL_YAML, page) is None


def test_redirect_to_id_provider_is_detected():
    page = FakePage(url="https://id.example.com/login?rp=demo", body="ログイン")
    assert "id.example.com" in _reason(MANUAL_YAML, page)


def test_missing_marker_element_is_detected():
    raw = dict(MANUAL_YAML,
               login=dict(MANUAL_YAML["login"],
                          success_check={"selector": ".mypage-header"}))
    assert "mypage-header" in _reason(raw, FakePage(url="https://example.com/mypage"))
    ok = FakePage(url="https://example.com/mypage", selectors=[".mypage-header"])
    assert _reason(raw, ok) is None


def test_logged_out_text_is_detected():
    raw = dict(MANUAL_YAML,
               login=dict(MANUAL_YAML["login"],
                          success_check={"logged_out_text": "新規会員登録"}))
    out = FakePage(url="https://example.com/", body="ログイン / 新規会員登録")
    assert "新規会員登録" in _reason(raw, out)
    assert _reason(raw, FakePage(url="https://example.com/", body="マイページ")) is None
