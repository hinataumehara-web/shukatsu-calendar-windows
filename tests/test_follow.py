"""詳細ページを辿って締切を読む仕組みのテスト

マイナビの一覧には「締切間近」としか出ておらず、日付は各社のコース情報
ページにしかない。そちらの構造（会社名はページ先頭、締切は下の方、
その手前にラベルと値が交互に並ぶ）から正しく取り出せることを確かめる。

ページの形は実物に合わせているが、会社名・コース名は架空のものにしてある。
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.scraper import GenericScraper  # noqa: E402
from engine.site_config import (  # noqa: E402
    SiteConfigError,
    build_variables,
    load_site_configs,
    parse_site_config,
)

REPO = Path(__file__).resolve().parents[1]


def mynavi_follow(listing_index: int = 0):
    """同梱のマイナビ定義から follow の設定を借りる"""
    sites = {s.slug: s for s in load_site_configs(
        REPO / "sites", build_variables({"settings": {"grad_year": 2028}}))}
    return sites["mynavi"].listings[listing_index].follow


# 実際のコース情報ページと同じ並び（会社名とコース名だけ架空のもの）
COURSE_PAGE = """最終更新日：2026/8/31
株式会社サンプル商事
業種
損害保険
基本情報
本社
東京都
お知らせ・イベント
エントリー
エントリー済
検討リスト登録済
会社概要
インターンシップ
＆キャリア
説明会・セミナー
インターンシップ＆キャリアとは
仕事体験
サンプル体験プログラム（全国支店開催）
開催地域
茨城 栃木 群馬 新潟 山梨 長野 静岡
開催時期
8月下旬～9月中旬予定
応募締切
2026年9月10日 応募締切あと6日
実施日数
2～4日
"""


def extract(text=COURSE_PAGE, follow=None):
    return GenericScraper.entries_from_detail(
        text, follow or mynavi_follow(), "https://example.com/corp1", "マイナビ")


# ------------------------------------------------------------ 基本の取り出し
def test_extracts_company_course_and_deadline():
    entries = extract()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.company == "株式会社サンプル商事"
    assert entry.deadline == date(2026, 9, 10)
    assert "サンプル体験プログラム（全国支店開催）" in entry.event_title
    assert entry.event_title.startswith("【マイナビ】")


def test_company_is_taken_from_the_top_not_from_above_the_deadline():
    """締切行の手前は「応募締切」などのラベルなので、会社名はページ先頭から取る"""
    assert extract()[0].company == "株式会社サンプル商事"


def test_last_updated_line_is_not_mistaken_for_the_company():
    assert "最終更新日" not in extract()[0].company


# ------------------------------------------------ コース名を汚さないこと
@pytest.mark.parametrize("noise", [
    "茨城 栃木 群馬 新潟 山梨 長野 静岡",   # 開催地域の羅列
    "8月下旬～9月中旬予定",                  # 開催時期の値
    "開催地域",
    "開催時期",
    "応募締切",
])
def test_labels_and_values_are_not_used_as_the_course_name(noise):
    assert noise not in extract()[0].event_title


def test_course_name_survives_extra_labels_before_the_deadline():
    """ラベルが増えても、コース名まで遡れること"""
    text = COURSE_PAGE.replace(
        "応募締切\n2026年9月10日",
        "募集人数\n30名\n報酬\nなし\n応募締切\n2026年9月10日")
    assert "サンプル体験プログラム（全国支店開催）" in extract(text)[0].event_title


# ------------------------------------------------------------ 複数・除外
def test_multiple_courses_become_multiple_entries():
    text = COURSE_PAGE + """別のプログラム（短期）
開催地域
東京
開催時期
10月上旬予定
応募締切
2026年10月20日 応募締切あと46日
"""
    entries = extract(text)
    assert len(entries) == 2
    assert {e.deadline for e in entries} == {date(2026, 9, 10), date(2026, 10, 20)}
    assert len({e.event_title for e in entries}) == 2


def test_closed_courses_are_skipped():
    text = COURSE_PAGE.replace("応募締切", "募集終了\n応募締切", 1)
    assert extract(text) == []


def test_page_without_a_deadline_yields_nothing():
    text = "最終更新日：2026/8/31\n株式会社サンプル商事\n現在、応募受付中のコースはありません。\n"
    assert extract(text) == []


def test_same_course_and_date_is_not_duplicated():
    assert len(extract(COURSE_PAGE + COURSE_PAGE)) == 1


# ------------------------------------------------------------ 設定の検証
def test_follow_is_configured_on_every_mynavi_listing():
    sites = {s.slug: s for s in load_site_configs(
        REPO / "sites", build_variables({"settings": {"grad_year": 2028}}))}
    for listing in sites["mynavi"].listings:
        assert listing.follow is not None
        assert listing.follow.link_text == "コース情報を見る"


def test_follow_has_a_page_limit_and_a_delay():
    """相手のサーバに連続アクセスしない設定になっていること"""
    follow = mynavi_follow()
    assert 1 <= follow.max_pages <= 50
    assert follow.delay_ms >= 1000


def test_link_text_is_required():
    raw = {"name": "t", "login": {"mode": "manual", "url": "https://e.com/"},
           "listings": [{"url": "https://e.com/list", "follow": {"max": 5}}]}
    with pytest.raises(SiteConfigError, match="link_text"):
        parse_site_config(raw, slug="t")


def test_page_limit_must_be_positive():
    raw = {"name": "t", "login": {"mode": "manual", "url": "https://e.com/"},
           "listings": [{"url": "https://e.com/list",
                         "follow": {"link_text": "詳細", "max": 0}}]}
    with pytest.raises(SiteConfigError, match="follow.max"):
        parse_site_config(raw, slug="t")


def test_unknown_company_pick_is_rejected():
    raw = {"name": "t", "login": {"mode": "manual", "url": "https://e.com/"},
           "listings": [{"url": "https://e.com/list",
                         "company": {"pick": "somewhere"}}]}
    with pytest.raises(SiteConfigError, match="company.pick"):
        parse_site_config(raw, slug="t")
