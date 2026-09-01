from datetime import date

from engine.dateparse import has_deadline_keyword, parse_date

TODAY = date(2026, 4, 17)


def test_full_date_formats():
    assert parse_date("2026年5月21日 23:59まで", TODAY) == date(2026, 5, 21)
    assert parse_date("2026/05/21", TODAY) == date(2026, 5, 21)
    assert parse_date("2026-05-21", TODAY) == date(2026, 5, 21)


def test_month_day_picks_nearest_future_year():
    # 年が省略されている場合、今日以降で最も近い年を選ぶ
    assert parse_date("5月21日締切", TODAY) == date(2026, 5, 21)
    assert parse_date("1月10日締切", TODAY) == date(2027, 1, 10)
    assert parse_date("4/20", TODAY) == date(2026, 4, 20)


def test_invalid_and_missing():
    assert parse_date("", TODAY) is None
    assert parse_date("締切はまだ未定です", TODAY) is None
    assert parse_date("2026年13月45日", TODAY) is None


def test_keyword_detection():
    assert has_deadline_keyword("エントリー締切")
    assert has_deadline_keyword("5月21日まで")
    assert not has_deadline_keyword("会社説明会のご案内")
