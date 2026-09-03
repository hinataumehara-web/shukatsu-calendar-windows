"""設定画面そのものを、画面を出さずに組み立てて確かめる

ウィジェットの綴り間違いや、保存処理の配線ミスは、実際に組み立ててみないと
分からない。tkinter や表示先が無い環境では丸ごとスキップする。
"""
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

tk = pytest.importorskip("tkinter", reason="tkinter が無い環境ではスキップ")


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


pytestmark = pytest.mark.skipif(
    not _display_available(),
    reason="画面（ディスプレイ）が無い環境ではスキップ。Linux では xvfb-run で実行できる",
)


@pytest.fixture
def gui(tmp_path, monkeypatch):
    """本物のリポジトリを汚さないよう、一時フォルダを作業先にした設定画面"""
    (tmp_path / "sites").mkdir()
    for src in (REPO / "sites").glob("*.yaml"):
        shutil.copy2(src, tmp_path / "sites" / src.name)
    shutil.copy2(REPO / "config.example.yaml", tmp_path / "config.example.yaml")
    shutil.copy2(REPO / ".env.example", tmp_path / ".env")

    import setup_gui

    monkeypatch.setattr(setup_gui, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(setup_gui, "CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(setup_gui, "CONFIG_EXAMPLE", str(tmp_path / "config.example.yaml"))
    monkeypatch.setattr(setup_gui, "KEY_FILE", str(tmp_path / "service_account.json"))

    window = setup_gui.SetupWindow()
    window.update()
    yield window, tmp_path
    window.destroy()


def test_window_builds_with_a_row_per_site(gui):
    window, _ = gui
    assert len(window.site_widgets) == len(window.site_rows)
    assert {"mynavi", "rikunabi", "type_shukatsu"} <= set(window.site_widgets)


def test_manual_and_automatic_sites_get_different_controls(gui):
    window, _ = gui
    # 手動ログインのサイトにパスワード欄は出さない
    assert "password" not in window.site_widgets["mynavi"]
    assert "state_label" in window.site_widgets["mynavi"]
    # 自動ログインのサイトには入力欄を出す
    assert "password" in window.site_widgets["type_shukatsu"]


def test_saving_writes_config_env_and_sites(gui):
    window, work = gui
    window.calendar_id.set("me@example.com")
    window.reminder_days.set("7, 3, 1")
    window.days_ahead.set("45")
    window.site_widgets["mynavi"]["enabled"].set(True)
    window.site_widgets["type_shukatsu"]["email"].set("a@b.com")
    window.site_widgets["type_shukatsu"]["password"].set("pw with space #1")

    assert window._save() is True

    config_text = (work / "config.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)
    assert config["google_calendar"]["calendar_id"] == "me@example.com"
    assert config["google_calendar"]["reminder_days"] == [7, 3, 1]
    assert config["settings"]["days_ahead"] == 45
    # 説明コメントが保存で消えていないこと
    assert "# 11 = Tomato（赤）" in config_text

    from engine import configfile
    env = configfile.load_env(str(work / ".env"))
    assert env["TYPE_SHUKATSU_EMAIL"] == "a@b.com"
    assert env["TYPE_SHUKATSU_PASSWORD"] == "pw with space #1"

    site = yaml.safe_load((work / "sites" / "mynavi.yaml").read_text(encoding="utf-8"))
    assert site["enabled"] is True


def test_saving_twice_is_stable(gui):
    """保存を繰り返しても設定ファイルが育っていかないこと"""
    window, work = gui
    window.calendar_id.set("me@example.com")
    window._save()
    first = (work / "config.yaml").read_text(encoding="utf-8")
    window._save()
    assert (work / "config.yaml").read_text(encoding="utf-8") == first


def test_reminder_days_accepts_japanese_comma(gui):
    window, work = gui
    window.reminder_days.set("5、2")
    window._save()
    config = yaml.safe_load((work / "config.yaml").read_text(encoding="utf-8"))
    assert config["google_calendar"]["reminder_days"] == [5, 2]


def test_blank_calendar_id_does_not_wipe_the_existing_one(gui):
    window, work = gui
    window.calendar_id.set("keep@example.com")
    window._save()
    window.calendar_id.set("   ")
    window._save()
    config = yaml.safe_load((work / "config.yaml").read_text(encoding="utf-8"))
    assert config["google_calendar"]["calendar_id"] == "keep@example.com"


def test_diagnosis_panel_shows_the_share_address(gui):
    window, _ = gui
    from engine import setup_ops

    window._show_google(setup_ops.Check(
        False, "カレンダーにアクセスできません", "共有してください",
        "shukatsu@demo.iam.gserviceaccount.com"))
    assert window.sa_email.get() == "shukatsu@demo.iam.gserviceaccount.com"
    shown = window.google_status.get("1.0", "end")
    assert "カレンダーにアクセスできません" in shown
    assert "共有してください" in shown
