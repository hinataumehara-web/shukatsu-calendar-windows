"""同梱のサイト定義が壊れていないことを検証する"""
import os

import pytest
import yaml

from engine.site_config import SiteConfigError, parse_site_config

SITES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sites")
SITE_FILES = sorted(f for f in os.listdir(SITES_DIR) if f.endswith((".yaml", ".yml")))


@pytest.mark.parametrize("filename", SITE_FILES)
def test_bundled_site_definitions_are_valid(filename):
    with open(os.path.join(SITES_DIR, filename), encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    site = parse_site_config(raw, slug=filename.rsplit(".", 1)[0])
    assert site.name
    assert site.listings


@pytest.mark.parametrize("filename", SITE_FILES)
def test_no_hardcoded_credentials(filename):
    """認証情報が YAML に直接書かれていないことを保証する"""
    with open(os.path.join(SITES_DIR, filename), encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    creds = raw.get("credentials") or {}
    assert "email" not in creds and "password" not in creds
    for key, value in creds.items():
        assert key.endswith("_env"), f"{key} は環境変数名で指定すること"
        assert "@" not in str(value), "メールアドレスを直接書かないこと"


def test_inline_credentials_are_rejected():
    raw = {
        "name": "bad",
        "credentials": {"email": "someone@example.com", "password": "hunter2"},
        "listings": [{"url": "https://example.com"}],
    }
    with pytest.raises(SiteConfigError):
        parse_site_config(raw, slug="bad")


def test_unknown_login_action_is_rejected():
    raw = {
        "name": "bad",
        "login": {"url": "https://example.com/login",
                  "steps": [{"action": "teleport", "selector": "#x"}]},
        "listings": [{"url": "https://example.com"}],
    }
    with pytest.raises(SiteConfigError):
        parse_site_config(raw, slug="bad")


def test_listing_is_required():
    with pytest.raises(SiteConfigError):
        parse_site_config({"name": "bad"}, slug="bad")
