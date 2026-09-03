"""ICS 書き出しのテスト

カレンダーソフトに読ませる前に、RFC 5545 で決まっている
「これを外すと読めなくなる」点を機械的に確かめる。
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import ics  # noqa: E402
from engine.models import DeadlineEntry  # noqa: E402


def entry(company="株式会社テスト", title="【インターン締切】3days 仕事体験",
          deadline=date(2026, 5, 21), source="マイナビ2027"):
    return DeadlineEntry(
        company=company, event_title=title, deadline=deadline,
        url="https://example.com/jobs", source=source,
        description=f"{company} / {title} / 締切 {deadline}",
    )


def unfold(text: str) -> list[str]:
    """折り返しを戻して論理行にする（受け取る側と同じ処理）"""
    lines = []
    for raw in text.split("\r\n"):
        if raw.startswith(" ") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


# ---------------------------------------------------------------- 構造
def test_calendar_wrapper_and_required_properties():
    logical = unfold(ics.build([entry()]))
    assert logical[0] == "BEGIN:VCALENDAR"
    assert logical[-1] == "END:VCALENDAR"
    assert "VERSION:2.0" in logical
    assert any(l.startswith("PRODID:") for l in logical)
    for prop in ("UID:", "DTSTAMP:", "DTSTART;VALUE=DATE:", "DTEND;VALUE=DATE:", "SUMMARY:"):
        assert any(l.startswith(prop) for l in logical), prop


def test_line_endings_are_crlf():
    text = ics.build([entry()])
    assert text.endswith("\r\n")
    # CRLF ではない裸の LF が混ざっていないこと
    assert "\n" not in text.replace("\r\n", "")


def test_no_line_exceeds_75_octets():
    long_entry = entry(company="と て も 長 い 名 前 の 株 式 会 社 " * 6,
                       title="【インターン締切】" + "非常に長いプログラム名" * 8)
    for line in ics.build([long_entry]).split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line


def test_folding_round_trips():
    company = "株式会社" + "あ" * 120
    logical = unfold(ics.build([entry(company=company)]))
    summary = next(l for l in logical if l.startswith("SUMMARY:"))
    assert company in summary


# ---------------------------------------------------------------- 終日予定
def test_all_day_event_ends_the_next_day():
    """DTEND は「終わりの翌日」を指す。同じ日にすると表示されないソフトがある"""
    logical = unfold(ics.build([entry(deadline=date(2026, 5, 21))]))
    assert "DTSTART;VALUE=DATE:20260521" in logical
    assert "DTEND;VALUE=DATE:20260522" in logical


def test_month_end_rolls_over():
    logical = unfold(ics.build([entry(deadline=date(2026, 12, 31))]))
    assert "DTEND;VALUE=DATE:20270101" in logical


# ---------------------------------------------------------------- 重複防止
def test_uid_is_stable_across_runs():
    """同じ締切なら毎回同じ UID。再インポートしても重複しない鍵になる"""
    assert ics.event_uid(entry()) == ics.event_uid(entry())


def test_uid_differs_per_deadline():
    uids = {
        ics.event_uid(entry()),
        ics.event_uid(entry(company="別の会社")),
        ics.event_uid(entry(deadline=date(2026, 6, 1))),
        ics.event_uid(entry(title="別のプログラム")),
    }
    assert len(uids) == 4


def test_rebuilding_gives_the_same_uids():
    entries = [entry(), entry(company="B社", deadline=date(2026, 6, 2))]
    first = {l for l in unfold(ics.build(entries)) if l.startswith("UID:")}
    second = {l for l in unfold(ics.build(list(reversed(entries)))) if l.startswith("UID:")}
    assert first == second


# ---------------------------------------------------------------- エスケープ
def test_special_characters_are_escaped():
    logical = unfold(ics.build([entry(company="A;B,C\\D", title="改行\nあり")]))
    summary = next(l for l in logical if l.startswith("SUMMARY:"))
    assert "A\\;B\\,C\\\\D" in summary
    assert "\\n" in summary
    # 生のセミコロン・カンマが値の中に残っていないこと
    assert ";" not in summary.split(":", 1)[1].replace("\\;", "")
    assert "," not in summary.split(":", 1)[1].replace("\\,", "")


# ---------------------------------------------------------------- 通知
def test_alarms_match_reminder_days():
    logical = unfold(ics.build([entry()], reminder_days=[3, 1]))
    assert logical.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-P3D" in logical
    assert "TRIGGER:-P1D" in logical


def test_no_alarms_when_disabled():
    logical = unfold(ics.build([entry()], reminder_days=[]))
    assert "BEGIN:VALARM" not in logical


# ---------------------------------------------------------------- 並び順・書き出し
def test_events_are_sorted_by_deadline():
    entries = [entry(company="後", deadline=date(2026, 7, 1)),
               entry(company="先", deadline=date(2026, 5, 1))]
    text = ics.build(entries)
    assert text.index("20260501") < text.index("20260701")


def test_write_keeps_crlf_on_disk(tmp_path):
    path = tmp_path / "out.ics"
    count = ics.write(str(path), [entry(), entry(company="B社")])
    assert count == 2
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert raw.decode("utf-8").startswith("BEGIN:VCALENDAR")
    # BOM を付けない（付けると読めないソフトがある）
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_empty_calendar_is_still_valid():
    logical = unfold(ics.build([]))
    assert logical[0] == "BEGIN:VCALENDAR"
    assert logical[-1] == "END:VCALENDAR"
    assert "BEGIN:VEVENT" not in logical


# ---------------------------------------------------------------- 起動まわり
def test_ics_mode_does_not_require_config_yaml():
    """友人に渡すときの肝。Google の設定が無い状態でも --ics は動き出せること"""
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    assert not (repo / "config.yaml").exists(), "テストは config.yaml が無い前提"

    result = subprocess.run(
        [sys.executable, str(repo / "main.py"), "--ics", "--list-sites"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(repo),
    )
    assert result.returncode == 0, result.stderr
    assert "config.yaml がありません" not in (result.stdout + result.stderr)
