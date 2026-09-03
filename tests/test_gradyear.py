"""卒業予定年の扱いのテスト

マイナビは URL に卒業年が入る（2028年卒なら /28/）。年度をサイト定義に
直接書くと、卒業年の違う人に渡すたびに書き換えが要る。config.yaml の
settings.grad_year から埋める仕組みが、正しく働くことを確かめる。
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.site_config import (  # noqa: E402
    build_variables,
    load_site_configs,
    parse_site_config,
    suggest_grad_year,
)

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ 候補の推定
@pytest.mark.parametrize("today,expected", [
    (date(2026, 9, 3), 2028),    # 2026年度の3年生 → 2028年卒
    (date(2026, 4, 1), 2028),    # 年度の始まり
    (date(2027, 3, 31), 2028),   # 年度の終わり。まだ2026年度
    (date(2027, 4, 1), 2029),    # 年度が変わると1つ進む
    (date(2026, 1, 15), 2027),   # 1月はまだ前の年度
])
def test_suggested_year_follows_the_japanese_school_year(today, expected):
    assert suggest_grad_year(today) == expected


# ------------------------------------------------------------------ 変数の生成
def test_variables_from_config():
    assert build_variables({"settings": {"grad_year": 2028}}) == {
        "grad_year": "2028", "grad_yy": "28"}


def test_variables_accept_a_string_value():
    """YAML で "2028" と書かれても動くこと"""
    assert build_variables({"settings": {"grad_year": "2028"}})["grad_yy"] == "28"


@pytest.mark.parametrize("config", [{}, {"settings": {}}, {"settings": {"grad_year": None}}])
def test_no_year_gives_no_variables(config):
    assert build_variables(config) == {}


# ------------------------------------------------------------------ URL の置換
@pytest.mark.parametrize("year,expected", [(2028, "/28/"), (2027, "/27/"), (2030, "/30/")])
def test_mynavi_urls_follow_the_configured_year(year, expected):
    sites = {s.slug: s for s in load_site_configs(
        REPO / "sites", build_variables({"settings": {"grad_year": year}}))}
    mynavi = sites["mynavi"]
    assert expected in mynavi.login_url
    assert all(expected in listing.url for listing in mynavi.listings)
    assert mynavi.unresolved_variables() == []


def test_unset_year_is_detected_instead_of_producing_a_broken_url():
    sites = {s.slug: s for s in load_site_configs(REPO / "sites")}
    assert sites["mynavi"].unresolved_variables() == ["grad_yy"]
    # 置き換えられないまま黙って使われることはない
    assert "{grad_yy}" in sites["mynavi"].login_url


def test_other_sites_are_unaffected():
    for variables in ({}, {"grad_year": "2028", "grad_yy": "28"}):
        sites = {s.slug: s for s in load_site_configs(REPO / "sites", variables)}
        for slug in ("rikunabi", "type_shukatsu", "bizreach_campus"):
            assert sites[slug].unresolved_variables() == [], slug


def test_credential_placeholders_in_login_steps_are_left_alone():
    """{email} や {password} は別の仕組み（実行時の置換）で扱う"""
    raw = {
        "name": "テスト",
        "credentials": {"email_env": "E", "password_env": "P"},
        "login": {"url": "https://example.com/{grad_yy}/login",
                  "steps": [{"action": "fill", "selector": "#a", "value": "{email}"}]},
        "listings": [{"url": "https://example.com/jobs"}],
    }
    site = parse_site_config(raw, slug="t", variables={"grad_yy": "28"})
    assert site.login_url == "https://example.com/28/login"
    assert site.login_steps[0]["value"] == "{email}"


def test_unknown_placeholder_is_left_for_the_error_message():
    raw = {"name": "テスト",
           "login": {"mode": "manual", "url": "https://example.com/{unknown}/x"},
           "listings": [{"url": "https://example.com/jobs"}]}
    site = parse_site_config(raw, slug="t", variables={"grad_yy": "28"})
    assert site.unresolved_variables() == ["unknown"]


# ------------------------------------------------------------------ 実行時の案内
def test_running_without_the_year_explains_what_to_set(tmp_path):
    """黙って空振りせず、どの設定を入れればよいかを名指しすること"""
    config = tmp_path / "config.yaml"
    config.write_text("google_calendar:\n  calendar_id: \"x@example.com\"\nsettings:\n  days_ahead: 90\n",
                      encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO / "main.py"), "--ics", "--site", "mynavi",
         "--config", str(config)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO),
    )
    combined = result.stdout + result.stderr
    assert "grad_year" in combined
    assert "卒業予定年" in combined


def test_list_sites_marks_sites_that_need_configuration(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("settings:\n  days_ahead: 90\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO / "main.py"), "--list-sites", "--config", str(config)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    mynavi_line = next(l for l in result.stdout.splitlines() if "mynavi" in l)
    assert "要設定" in mynavi_line and "grad_yy" in mynavi_line
