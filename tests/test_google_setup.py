"""Google へのつなぎ方の判定テスト

google 系ライブラリを入れずに動く範囲（状態判定・パス解決・案内文）を確かめる。
実際のログインはブラウザが要るのでここでは扱わない。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import google_setup as gs  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

VALID_CLIENT = {"installed": {
    "client_id": "123456789-abcdef.apps.googleusercontent.com",
    "client_secret": "GOCSPX-xxxxxxxxxxxx",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}}


def write(path: Path, data) -> Path:
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


# ------------------------------------------------------------------ パス解決
def test_paths_use_defaults(tmp_path):
    p = gs.paths(str(tmp_path))
    assert p["oauth_client"].endswith("oauth_client.json")
    assert p["token"].endswith("token.json")
    assert p["service_account"].endswith("service_account.json")
    assert all(Path(v).parent == tmp_path for v in p.values())


def test_paths_respect_config_overrides(tmp_path):
    p = gs.paths(str(tmp_path), {"token_file": "sub/mine.json"})
    assert p["token"] == str(tmp_path / "sub" / "mine.json")


def test_paths_keep_absolute_values(tmp_path):
    absolute = str(tmp_path / "elsewhere.json")
    assert gs.paths(str(tmp_path), {"token_file": absolute})["token"] == absolute


# ------------------------------------------------ OAuth クライアントの有無
def test_no_client_file(tmp_path):
    assert gs.has_oauth_client(str(tmp_path)) is False


def test_placeholder_client_counts_as_missing(tmp_path):
    """雛形のまま配られても「用意済み」と誤判定しないこと"""
    write(tmp_path / "oauth_client.json",
          {"installed": {"client_id": "ここに発行された client_id を貼る"}})
    assert gs.has_oauth_client(str(tmp_path)) is False


def test_broken_client_file_counts_as_missing(tmp_path):
    write(tmp_path / "oauth_client.json", "{ broken")
    assert gs.has_oauth_client(str(tmp_path)) is False


def test_real_client_is_detected(tmp_path):
    write(tmp_path / "oauth_client.json", VALID_CLIENT)
    assert gs.has_oauth_client(str(tmp_path)) is True


def test_shipped_example_is_only_a_template():
    """同梱の雛形が、そのままでは有効と判定されないこと"""
    example = REPO / "oauth_client.example.json"
    assert example.exists(), "配る人向けの雛形が無い"
    data = json.loads(example.read_text(encoding="utf-8"))
    assert "installed" in data


# ------------------------------------------------------------------ 状態判定
def test_nothing_configured_points_at_ics(tmp_path):
    state = gs.status(str(tmp_path))
    assert state.connected is False
    assert state.method == "none"
    assert "ICS" in state.detail


def test_client_present_but_not_logged_in(tmp_path):
    write(tmp_path / "oauth_client.json", VALID_CLIENT)
    state = gs.status(str(tmp_path))
    assert state.connected is False
    assert "ログイン" in state.detail


def test_token_means_connected(tmp_path):
    write(tmp_path / "oauth_client.json", VALID_CLIENT)
    write(tmp_path / "token.json", {"refresh_token": "x"})
    state = gs.status(str(tmp_path))
    assert state.method == "oauth"
    assert state.connected is True


def test_service_account_wins_over_oauth(tmp_path):
    """両方あるときは、無人運転できるサービスアカウントを優先する"""
    write(tmp_path / "token.json", {"refresh_token": "x"})
    write(tmp_path / "service_account.json", {"type": "service_account"})
    assert gs.status(str(tmp_path)).method == "service_account"


# ------------------------------------------------------------------ 案内・権限
def test_connect_without_a_client_explains_instead_of_crashing(tmp_path):
    state = gs.connect(str(tmp_path))
    assert state.ok is False
    assert state.method == "none"


def test_load_credentials_without_token_names_the_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="--connect-google"):
        gs.load_credentials(str(tmp_path))


def test_oauth_scope_is_narrow():
    """予定の読み書きだけ。カレンダーの作成・削除まで求めない"""
    assert gs.OAUTH_SCOPES == ["https://www.googleapis.com/auth/calendar.events"]


def test_calendar_client_never_opens_a_browser():
    """定期実行の最中にログイン画面が開くと、静かに固まる

    ログインは google_setup.connect() だけが行う。
    """
    source = (REPO / "engine" / "calendar_client.py").read_text(encoding="utf-8")
    assert "InstalledAppFlow" not in source
    assert "run_local_server" not in source


def test_calendar_client_no_longer_uses_pickle():
    """pickle 形式のトークンは読み込み自体が危ういので使わない"""
    source = (REPO / "engine" / "calendar_client.py").read_text(encoding="utf-8")
    assert "pickle" not in source
