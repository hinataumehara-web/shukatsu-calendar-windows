"""検出した締切を iCalendar (.ics) ファイルとして書き出す

なぜこれがあるのか
------------------
Google Calendar API を使う方式は、動き出せば快適だが、使い始めるまでに
Google Cloud でプロジェクトを作り、API を有効化し、サービスアカウントを作り、
鍵をダウンロードし、カレンダーを共有する、という20分ほどの作業が要る。
人に勧めるとき、ここで確実に脱落する。

ICS 方式なら、その作業がまるごと要らない。ファイルを1つ吐くだけで、
あとはカレンダー側の「インポート」に食わせればよい。

重複について
------------
各予定の UID を「出典・企業名・タイトル・締切日」から決まる固定値にしてある。
Google カレンダーも Outlook も、インポート時に UID が同じ予定は
「新規追加」ではなく「既存の更新」として扱う。つまり毎日実行して
毎回インポートし直しても、同じ締切が二重に増えることはない。

仕様は RFC 5545。特に次の3点は、守らないと読み込めないカレンダーがある。
  - 行末は CRLF
  - 1行は75オクテットまで。超えたら次行の先頭に空白1つを置いて折り返す
  - テキスト中の \\ ; , 改行 はエスケープする
"""
import hashlib
from datetime import date, datetime, timedelta, timezone

PRODID = "-//shukatsu-calendar//JP"
UID_DOMAIN = "shukatsu-calendar"

# 1行の上限（オクテット）。CRLF を除いた本体の長さ
MAX_OCTETS = 75


def _escape(text: str) -> str:
    """RFC 5545 のテキスト値としてエスケープする"""
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> list[str]:
    """75オクテットで折り返す（日本語が途中で切れないよう文字単位で数える）"""
    out = []
    current = ""
    current_len = 0
    limit = MAX_OCTETS
    for ch in line:
        size = len(ch.encode("utf-8"))
        if current_len + size > limit:
            out.append(current)
            # 継続行は先頭の空白1文字分を消費する
            current = " " + ch
            current_len = 1 + size
            limit = MAX_OCTETS
        else:
            current += ch
            current_len += size
    out.append(current)
    return out


def _date_value(d: date) -> str:
    return d.strftime("%Y%m%d")


def _timestamp(now: datetime = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def event_uid(entry) -> str:
    """同じ締切なら毎回同じになる UID（重複登録を防ぐ鍵）"""
    digest = hashlib.sha1(entry.key().encode("utf-8")).hexdigest()
    return f"{digest}@{UID_DOMAIN}"


def _event_lines(entry, event_tag: str, reminder_days, dtstamp: str) -> list[str]:
    summary = f"{event_tag} {entry.company} {entry.event_title}".strip()
    description = (
        f"出典: {entry.source}\n"
        f"URL: {entry.url}\n"
        f"詳細: {entry.description}"
    )

    lines = [
        "BEGIN:VEVENT",
        f"UID:{event_uid(entry)}",
        f"DTSTAMP:{dtstamp}",
        # 終日予定。DTEND は「終わりの翌日」を指す決まり
        f"DTSTART;VALUE=DATE:{_date_value(entry.deadline)}",
        f"DTEND;VALUE=DATE:{_date_value(entry.deadline + timedelta(days=1))}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
        "TRANSP:TRANSPARENT",
        "SEQUENCE:0",
    ]
    if entry.url:
        lines.append(f"URL:{_escape(entry.url)}")

    for days in reminder_days or []:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:-P{int(days)}D",
            f"DESCRIPTION:{_escape(f'{int(days)}日後が締切: {summary}')}",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build(entries, event_tag: str = "[就活自動登録]", reminder_days=(3, 1),
          calendar_name: str = "就活の締切", now: datetime = None) -> str:
    """締切のリストから .ics の中身（文字列）を作る"""
    dtstamp = _timestamp(now)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    # 締切が近い順に並べる（インポート結果を目で確認しやすい）
    for entry in sorted(entries, key=lambda e: (e.deadline, e.company)):
        lines += _event_lines(entry, event_tag, reminder_days, dtstamp)
    lines.append("END:VCALENDAR")

    folded = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"


def write(path: str, entries, **kwargs) -> int:
    """.ics を書き出して、書いた件数を返す"""
    text = build(entries, **kwargs)
    # newline="" にしないと、Windows で CRLF が CRCRLF になる
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return len(list(entries))
