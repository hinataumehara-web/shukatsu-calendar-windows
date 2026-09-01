"""実行環境まわり（特に Windows 対応）の回帰テスト"""
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import runtime  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def test_user_agent_matches_platform():
    ua = runtime.default_user_agent()
    if runtime.IS_WINDOWS:
        assert "Windows NT" in ua
    else:
        assert "Macintosh" in ua


def test_configure_stdio_survives_missing_stdout(monkeypatch):
    """pythonw.exe では sys.stdout が None になる。落ちてはいけない。"""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    runtime.configure_stdio()          # 例外を出さないこと
    assert runtime.has_console() is False


def test_setup_is_idempotent():
    runtime.setup()
    runtime.setup()


def test_log_file_handles_non_cp932_characters(tmp_path):
    """絵文字入りの企業名でもログが書けること（Windows の既定は cp932）"""
    log_path = tmp_path / "test.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logger = logging.getLogger("shukatsu_test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("株式会社テスト 🎓 / 締切 2026-05-21")
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert "🎓" in log_path.read_text(encoding="utf-8")


def test_batch_files_are_ascii_and_crlf():
    """cmd.exe が読めるように .bat は ASCII + CRLF で保存する"""
    for bat in sorted(REPO.glob("*.bat")):
        raw = bat.read_bytes()
        raw.decode("ascii")                       # 非ASCIIが混ざっていないこと
        assert b"\r\n" in raw, f"{bat.name} が CRLF ではありません"
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{bat.name} に裸の LF があります"


def test_main_py_rejects_old_python_before_syntax_error():
    """3.9 以下でも「Python 3.10 以上が必要」と言える位置に判定があること

    main.py の先頭から `str | None` を含む行までの間にバージョン判定が
    無いと、古い Python では意味の分からない TypeError で落ちる。
    """
    text = (REPO / "main.py").read_text(encoding="utf-8")
    guard = text.index("sys.version_info < (3, 10)")
    first_new_syntax = text.index("str | None")
    assert guard < first_new_syntax


@pytest.mark.skipif(not (REPO / "config.example.yaml").exists(), reason="設定例が無い")
def test_list_sites_runs():
    """Playwright 無しでも --list-sites は動くこと"""
    result = subprocess.run(
        [sys.executable, str(REPO / "main.py"), "--list-sites",
         "--config", str(REPO / "config.example.yaml")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
