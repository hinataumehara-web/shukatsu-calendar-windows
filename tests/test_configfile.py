"""設定ファイルの書き換えテスト

GUI から保存するたびにコメントが消える、値が壊れる、といった事故を防ぐ。
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import configfile as cf  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

SAMPLE_CONFIG = '''# config.yaml のひな形
#     copy config.example.yaml config.yaml

google_calendar:
  # 予定を書き込むカレンダーの ID
  calendar_id: "you@example.com"
  service_account_file: "service_account.json"
  event_tag: "[就活自動登録]"
  color_id: "11"          # 11 = Tomato（赤）
  reminder_days: [3, 1]   # 何日前に通知するか

settings:
  days_ahead: 90              # 何日先までの締切を対象にするか
  headless: true              # false にするとブラウザが表示される
  log_file: "shukatsu.log"
'''


# ------------------------------------------------------------------ .env
def test_env_roundtrip_keeps_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# コピーして .env を作る\n"
        "# 変数名は sites/*.yaml と一致させる\n"
        "\n"
        "TYPE_SHUKATSU_EMAIL=\n"
        "TYPE_SHUKATSU_PASSWORD=\n",
        encoding="utf-8")

    cf.apply_env(str(path), {"TYPE_SHUKATSU_EMAIL": "me@example.com",
                             "TYPE_SHUKATSU_PASSWORD": "p@ssw0rd"})

    text = path.read_text(encoding="utf-8")
    assert "# コピーして .env を作る" in text
    assert "# 変数名は sites/*.yaml と一致させる" in text
    values = cf.load_env(str(path))
    assert values["TYPE_SHUKATSU_EMAIL"] == "me@example.com"
    assert values["TYPE_SHUKATSU_PASSWORD"] == "p@ssw0rd"


def test_env_appends_unknown_keys(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")
    cf.apply_env(str(path), {"B": "2"})
    assert cf.load_env(str(path)) == {"A": "1", "B": "2"}


def test_env_none_values_are_left_alone(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=keep\n", encoding="utf-8")
    cf.apply_env(str(path), {"A": None, "B": "new"})
    assert cf.load_env(str(path)) == {"A": "keep", "B": "new"}


@pytest.mark.parametrize("password", [
    "simple",
    "with space",
    "hash#inside",
    'quote"inside',
    "apostrophe'inside",
    "  padded  ",
    "記号!@$%^&*()_+-=",
])
def test_env_password_survives_roundtrip(tmp_path, password):
    """パスワードは何が入っていてもおかしくない。壊さずに読み戻せること"""
    path = tmp_path / ".env"
    cf.apply_env(str(path), {"PW": password})
    assert cf.load_env(str(path))["PW"] == password


def test_env_reads_bom(tmp_path):
    """メモ帳や PowerShell の > は BOM を付ける"""
    path = tmp_path / ".env"
    path.write_bytes("\ufeffA=1\n".encode("utf-8"))
    assert cf.load_env(str(path)) == {"A": "1"}


def test_strip_quotes_only_removes_matching_pairs():
    assert cf.strip_quotes('"abc"') == "abc"
    assert cf.strip_quotes("'abc'") == "abc"
    assert cf.strip_quotes('abc"') == 'abc"'      # 末尾が " のパスワードを壊さない
    assert cf.strip_quotes('"abc') == '"abc'
    assert cf.strip_quotes("abc") == "abc"


# ------------------------------------------------------------------ YAML
def test_yaml_edit_keeps_comments_and_order(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")

    cf.set_yaml_values(str(path), {
        "google_calendar.calendar_id": "hinata@example.com",
        "settings.days_ahead": 60,
        "settings.headless": False,
    })

    text = path.read_text(encoding="utf-8")
    assert "# config.yaml のひな形" in text
    assert "# 予定を書き込むカレンダーの ID" in text
    assert "# 11 = Tomato（赤）" in text            # 行末コメントも残る
    assert "# 何日先までの締切を対象にするか" in text

    data = yaml.safe_load(text)
    assert data["google_calendar"]["calendar_id"] == "hinata@example.com"
    assert data["settings"]["days_ahead"] == 60
    assert data["settings"]["headless"] is False
    # 触っていない値はそのまま
    assert data["google_calendar"]["event_tag"] == "[就活自動登録]"
    assert data["google_calendar"]["reminder_days"] == [3, 1]
    assert data["settings"]["log_file"] == "shukatsu.log"


def test_yaml_list_value(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    cf.set_yaml_values(str(path), {"google_calendar.reminder_days": [7, 3, 1]})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["google_calendar"]["reminder_days"] == [7, 3, 1]


def test_yaml_missing_key_is_added_under_its_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    cf.set_yaml_values(str(path), {"google_calendar.calendar_name": "就活"})
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["google_calendar"]["calendar_name"] == "就活"


def test_yaml_same_key_in_two_sections_is_not_confused(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("a:\n  name: one\nb:\n  name: two\n", encoding="utf-8")
    cf.set_yaml_values(str(path), {"b.name": "changed"})
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["a"]["name"] == "one"
    assert data["b"]["name"] == "changed"


def test_yaml_commented_out_key_is_not_edited(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("settings:\n  # days_ahead: 999\n  days_ahead: 90\n", encoding="utf-8")
    cf.set_yaml_values(str(path), {"settings.days_ahead": 30})
    text = path.read_text(encoding="utf-8")
    assert "# days_ahead: 999" in text
    assert yaml.safe_load(text)["settings"]["days_ahead"] == 30


@pytest.mark.parametrize("value", ["yes", "no", "null", "12:30", "on", "3.5", "[]", "#tag"])
def test_yaml_tricky_strings_stay_strings(tmp_path, value):
    """囲まないと bool や数値に化ける値がある"""
    path = tmp_path / "c.yaml"
    path.write_text('g:\n  v: "x"\n', encoding="utf-8")
    cf.set_yaml_values(str(path), {"g.v": value})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["g"]["v"] == value


# ------------------------------------------------------------------ サイト定義
def test_site_enabled_toggle_keeps_the_rest(tmp_path):
    path = tmp_path / "site.yaml"
    original = (REPO / "sites" / "type_shukatsu.yaml").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")

    assert cf.read_site_enabled(str(path)) is True
    cf.set_site_enabled(str(path), False)
    assert cf.read_site_enabled(str(path)) is False

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["enabled"] is False
    assert data["name"] == "type就活"
    assert data["login"]["steps"], "ログイン手順が消えている"
    assert "# type就活" in path.read_text(encoding="utf-8")

    cf.set_site_enabled(str(path), True)
    assert cf.read_site_enabled(str(path)) is True


def test_every_bundled_site_can_be_toggled(tmp_path):
    """同梱の定義すべてで、切り替えても YAML として壊れないこと"""
    for src in sorted((REPO / "sites").glob("*.yaml")):
        path = tmp_path / src.name
        path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        for value in (True, False, True):
            cf.set_site_enabled(str(path), value)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert data["enabled"] is value, src.name
            assert data["name"], src.name
