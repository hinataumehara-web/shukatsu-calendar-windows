"""設定画面が使う処理のテスト（画面は出さない）"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import configfile, setup_ops  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

VALID_KEY = {
    "type": "service_account",
    "project_id": "demo",
    "private_key_id": "x",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "shukatsu@demo.iam.gserviceaccount.com",
    "client_id": "1",
}


@pytest.fixture
def workdir(tmp_path):
    """sites/ と .env を持つ、本物に似た作業フォルダ"""
    (tmp_path / "sites").mkdir()
    for src in (REPO / "sites").glob("*.yaml"):
        shutil.copy2(src, tmp_path / "sites" / src.name)
    shutil.copy2(REPO / ".env.example", tmp_path / ".env")
    return tmp_path


# ------------------------------------------------------------ 実行ファイル探し
def test_python_exe_missing_venv(tmp_path):
    assert setup_ops.python_exe(str(tmp_path)) == ""


@pytest.mark.parametrize("relative", [
    ("\\".join([".venv", "Scripts", "python.exe"])),
    ("/".join([".venv", "bin", "python"])),
])
def test_python_exe_finds_either_layout(tmp_path, relative):
    path = tmp_path / Path(relative.replace("\\", "/"))
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    assert setup_ops.python_exe(str(tmp_path)) == str(path).replace("/", os.sep)


# ------------------------------------------------------------------ 鍵の判定
def test_key_file_missing(tmp_path):
    check = setup_ops.read_service_account(str(tmp_path / "nope.json"))
    assert check.ok is False
    assert "見つかりません" in check.title


def test_key_file_broken_json(tmp_path):
    path = tmp_path / "k.json"
    path.write_text("{ this is not json", encoding="utf-8")
    check = setup_ops.read_service_account(str(path))
    assert check.ok is False
    assert "読めません" in check.title


def test_oauth_file_is_recognised_and_explained(tmp_path):
    """よくある取り違え。OAuth のファイルを鍵として置いてしまうケース"""
    path = tmp_path / "k.json"
    path.write_text(json.dumps({"type": "authorized_user", "client_id": "x"}), encoding="utf-8")
    check = setup_ops.read_service_account(str(path))
    assert check.ok is False
    assert "OAuth" in check.title
    assert "サービス アカウント" in check.detail


def test_valid_key_returns_share_address(tmp_path):
    path = tmp_path / "k.json"
    path.write_text(json.dumps(VALID_KEY), encoding="utf-8")
    check = setup_ops.read_service_account(str(path))
    assert check.ok is True
    assert check.sa_email == "shukatsu@demo.iam.gserviceaccount.com"


def test_key_with_bom_is_accepted(tmp_path):
    path = tmp_path / "k.json"
    path.write_bytes("﻿".encode("utf-8") + json.dumps(VALID_KEY).encode("utf-8"))
    assert setup_ops.read_service_account(str(path)).ok is True


# --------------------------------------------------------------- Google 診断
def _with_key(tmp_path):
    (tmp_path / "service_account.json").write_text(json.dumps(VALID_KEY), encoding="utf-8")
    return str(tmp_path)


def test_empty_calendar_id_is_caught_before_network(tmp_path):
    check = setup_ops.check_google(_with_key(tmp_path), "")
    assert check.ok is False
    assert "カレンダー ID" in check.title
    assert check.sa_email  # 共有先は先に見せてあげる


def test_primary_is_rejected_with_the_reason(tmp_path):
    check = setup_ops.check_google(_with_key(tmp_path), "primary")
    assert check.ok is False
    assert "primary" in check.title


def test_missing_google_libraries_points_at_the_installer(tmp_path):
    """google 系が未導入のときは、次にやることを名指しする"""
    pytest.importorskip  # noqa: B018
    try:
        import googleapiclient  # noqa: F401
        pytest.skip("google ライブラリが入っている環境ではこの分岐を通らない")
    except ImportError:
        pass
    check = setup_ops.check_google(_with_key(tmp_path), "me@example.com")
    assert check.ok is False
    assert "setup_google.bat" in check.detail


# ---------------------------------------------------------- タスクスケジューラ
def test_create_task_args_pads_the_time():
    args = setup_ops.create_task_args("/tmp/app", 8)
    assert "08:00" in args
    assert args[:2] == ["schtasks", "/create"]
    assert "/f" in args                      # 既存タスクを黙って上書きできる
    assert setup_ops.TASK_NAME in args


def test_create_task_args_accepts_minutes():
    assert "07:30" in setup_ops.create_task_args("/tmp/app", 7, 30)


def test_task_command_quotes_paths_with_spaces():
    command = setup_ops.task_command("/home/My Files/app")
    assert command.count('"') == 4          # 実行ファイルとスクリプトの両方を囲む
    assert "My Files" in command


def test_delete_and_query_args_name_the_task():
    assert setup_ops.TASK_NAME in setup_ops.delete_task_args()
    assert setup_ops.TASK_NAME in setup_ops.query_task_args()


def test_schtasks_refuses_politely_off_windows():
    if setup_ops.scheduler_available():
        pytest.skip("Windows ではこの分岐を通らない")
    ok, message = setup_ops.run_schtasks(setup_ops.query_task_args())
    assert ok is False
    assert "Windows" in message


# ------------------------------------------------------------------ サイト一覧
def test_list_sites_reports_login_style(workdir):
    rows = {r.slug: r for r in setup_ops.list_sites(str(workdir))}
    assert rows["mynavi"].manual_login is True
    assert rows["mynavi"].needs_credentials is False
    assert rows["type_shukatsu"].manual_login is False
    assert rows["type_shukatsu"].needs_credentials is True
    assert rows["type_shukatsu"].email_env == "TYPE_SHUKATSU_EMAIL"


def test_list_sites_prefills_saved_credentials(workdir):
    configfile.apply_env(str(workdir / ".env"), {"TYPE_SHUKATSU_EMAIL": "me@example.com"})
    rows = {r.slug: r for r in setup_ops.list_sites(str(workdir))}
    assert rows["type_shukatsu"].env_values["email"] == "me@example.com"


def test_save_sites_writes_both_yaml_and_env(workdir):
    rows = setup_ops.list_sites(str(workdir))
    by_slug = {r.slug: r for r in rows}
    by_slug["mynavi"].enabled = True
    by_slug["type_shukatsu"].enabled = False
    by_slug["type_shukatsu"].env_values = {"email": "a@b.com", "password": "秘密 #1"}

    setup_ops.save_sites(str(workdir), rows)

    assert yaml.safe_load((workdir / "sites" / "mynavi.yaml").read_text(encoding="utf-8"))["enabled"] is True
    assert yaml.safe_load((workdir / "sites" / "type_shukatsu.yaml").read_text(encoding="utf-8"))["enabled"] is False

    env = configfile.load_env(str(workdir / ".env"))
    assert env["TYPE_SHUKATSU_EMAIL"] == "a@b.com"
    assert env["TYPE_SHUKATSU_PASSWORD"] == "秘密 #1"


def test_save_sites_survives_a_round_trip(workdir):
    """保存 → 読み直し → 保存 で内容が変わらないこと"""
    rows = setup_ops.list_sites(str(workdir))
    for row in rows:
        if row.needs_credentials:
            row.env_values = {"email": "x@example.com", "password": "pw"}
    setup_ops.save_sites(str(workdir), rows)
    first = (workdir / "sites" / "type_shukatsu.yaml").read_text(encoding="utf-8")

    again = setup_ops.list_sites(str(workdir))
    setup_ops.save_sites(str(workdir), again)
    assert (workdir / "sites" / "type_shukatsu.yaml").read_text(encoding="utf-8") == first
