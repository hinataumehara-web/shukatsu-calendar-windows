"""日本語の求人ページによく出てくる日付表記のパーサ"""
import re
from datetime import date
from typing import Optional

# 「締切」を示す語。サイト定義で match: keyword を使うときの既定値
DEADLINE_KEYWORDS = [
    "締切", "〆切", "締め切り", "エントリー期限", "応募期限",
    "期限", "まで", "応募締切", "エントリー締切",
]

_FULL_DATE = re.compile(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})日?")
_MONTH_DAY_JP = re.compile(r"(\d{1,2})月(\d{1,2})日")
_MONTH_DAY_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


def parse_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """テキストから最初に見つかった日付を返す。

    年が省略されている場合は「今日以降で最も近い年」を採用する。
    （3月に「1月10日」とあれば翌年の1月10日と解釈する）
    """
    if not text:
        return None
    today = today or date.today()

    m = _FULL_DATE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    for pattern in (_MONTH_DAY_JP, _MONTH_DAY_SLASH):
        m = pattern.search(text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            for year in (today.year, today.year + 1):
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                if d >= today:
                    return d
    return None


def has_deadline_keyword(text: str, keywords=None) -> bool:
    return any(kw in text for kw in (keywords or DEADLINE_KEYWORDS))
