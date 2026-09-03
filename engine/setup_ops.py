"""セットアップ画面が使う処理（画面から切り離してある）

tkinter のウィジェット組み立てと、実際にやることを分けておく。
こうしておくと、画面を出さずにここだけテストできる。
"""
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from . import configfile, runtime, session
from .site_config import (
    build_variables,
    load_site_configs,
    suggest_grad_year,
)

TASK_NAME = "shukatsu-calendar"


# --------------------------------------------------------------- 実行ファイル
def python_exe(base_dir: str) -> str:
    """このリポジトリの仮想環境の Python。無ければ空文字"""
    candidates = (
        os.path.join(base_dir, ".venv", "Scripts", "python.exe"),   # Windows
        os.path.join(base_dir, ".venv", "bin", "python"),           # mac / Linux
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def pythonw_exe(base_dir: str) -> str:
    """コンソールを出さない Python（Windows のみ）。無ければ通常の python"""
    quiet = os.path.join(base_dir, ".venv", "Scripts", "pythonw.exe")
    return quiet if os.path.isfile(quiet) else python_exe(base_dir)


# ------------------------------------------------------------------- サイト
def load_config(base_dir: str) -> dict:
    """config.yaml を読む。無ければ空（設定画面は config.yaml 無しでも開ける）"""
    import yaml

    path = os.path.join(base_dir, "config.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


def grad_year(base_dir: str) -> int:
    """設定済みの卒業予定年。未設定なら今の学年から推定した候補を返す"""
    value = (load_config(base_dir).get("settings") or {}).get("grad_year")
    try:
        return int(value)
    except (TypeError, ValueError):
        return suggest_grad_year()


@dataclass
class SiteRow:
    """画面に1行として出すサイトの状態"""
    slug: str
    name: str
    enabled: bool
    manual_login: bool
    email_env: str = ""
    password_env: str = ""
    session_state: str = ""
    path: str = ""
    env_values: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)

    @property
    def needs_credentials(self) -> bool:
        return bool(self.email_env or self.password_env)


def list_sites(base_dir: str) -> list:
    env = configfile.load_env(os.path.join(base_dir, ".env"))
    variables = build_variables(load_config(base_dir))
    rows = []
    for site in load_site_configs(os.path.join(base_dir, "sites"), variables):
        rows.append(SiteRow(
            slug=site.slug,
            name=site.name,
            enabled=site.enabled,
            manual_login=site.uses_saved_session(),
            email_env=site.email_env,
            password_env=site.password_env,
            session_state=session.describe(base_dir, site.slug) if site.uses_saved_session() else "",
            path=os.path.join(base_dir, "sites", f"{site.slug}.yaml"),
            unresolved=site.unresolved_variables(),
            env_values={
                "email": env.get(site.email_env, ""),
                "password": env.get(site.password_env, ""),
            },
        ))
    return rows


def save_sites(base_dir: str, rows: list) -> None:
    """画面の内容を sites/*.yaml と .env に書き戻す"""
    updates = {}
    for row in rows:
        configfile.set_site_enabled(row.path, row.enabled)
        if row.email_env:
            updates[row.email_env] = row.env_values.get("email", "")
        if row.password_env:
            updates[row.password_env] = row.env_values.get("password", "")
    if updates:
        configfile.apply_env(os.path.join(base_dir, ".env"), updates)


# ------------------------------------------------------------------ Google
@dataclass
class Check:
    ok: bool
    title: str
    detail: str = ""
    sa_email: str = ""


def read_service_account(path: str) -> Check:
    """鍵ファイルを開かずに分かる問題を先に潰す（ネットワーク不要）"""
    if not os.path.isfile(path):
        return Check(False, "service_account.json が見つかりません",
                     "Google Cloud で作ったサービスアカウントの JSON 鍵を、\n"
                     "「鍵を選ぶ…」から取り込んでください。")
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return Check(False, "鍵ファイルを読めません", f"JSON として壊れています: {e}")

    if data.get("type") == "authorized_user":
        return Check(False, "これは OAuth のファイルです",
                     "サービスアカウントの鍵ではありません。Google Cloud の\n"
                     "「サービス アカウント」→「キー」→「鍵を追加」→ JSON で作り直してください。")
    if data.get("type") != "service_account" or not data.get("client_email"):
        return Check(False, "サービスアカウントの鍵ではないようです",
                     "ダウンロードしたファイルを取り違えている可能性があります。")

    return Check(True, "鍵ファイルを確認しました", sa_email=data["client_email"])


def check_google(base_dir: str, calendar_id: str) -> Check:
    """鍵・カレンダーID・共有設定まで、順に確かめて最初の問題を返す"""
    key_path = os.path.join(base_dir, "service_account.json")
    key = read_service_account(key_path)
    if not key.ok:
        return key
    sa_email = key.sa_email

    calendar_id = (calendar_id or "").strip()
    if not calendar_id:
        return Check(False, "カレンダー ID が空です",
                     "Google カレンダーの「設定と共有」に出ているカレンダー ID を入れてください。\n"
                     "自分のメインカレンダーなら、自分のメールアドレスです。", sa_email)
    if calendar_id == "primary":
        return Check(False, 'カレンダー ID に "primary" は使えません',
                     "primary はサービスアカウント自身の（誰にも見えない）カレンダーを指します。\n"
                     "自分のカレンダー ID を入れてください。", sa_email)

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return Check(False, "Google API 用のライブラリが入っていません",
                     "setup_google.bat を実行してください。\n"
                     "（Google を使わない ICS 方式なら、この設定は不要です）", sa_email)

    try:
        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=["https://www.googleapis.com/auth/calendar"])
        service = build("calendar", "v3", credentials=creds)
        info = service.calendars().get(calendarId=calendar_id).execute()
    except Exception as e:
        return Check(
            False, "カレンダーにアクセスできません",
            f"{_short_error(e)}\n\n"
            "Google カレンダーの「設定と共有」→「特定のユーザーやグループと共有する」で、\n"
            "下のアドレスに「予定の変更権限」を与えてください。\n"
            "（共有直後は反映まで少し時間がかかることがあります）", sa_email)

    return Check(True, f"接続できました: {info.get('summary', calendar_id)}",
                 "このままカレンダーへ登録できます。", sa_email)


def _short_error(e: Exception) -> str:
    text = str(e)
    return text if len(text) <= 300 else text[:300] + "..."


# ---------------------------------------------------------- タスクスケジューラ
def task_command(base_dir: str) -> str:
    """schtasks の /tr に渡す文字列"""
    return f'"{pythonw_exe(base_dir)}" "{os.path.join(base_dir, "main.py")}"'


def create_task_args(base_dir: str, hour: int, minute: int = 0,
                     task_name: str = TASK_NAME) -> list:
    return [
        "schtasks", "/create", "/f",
        "/tn", task_name,
        "/sc", "daily",
        "/st", f"{int(hour):02d}:{int(minute):02d}",
        "/tr", task_command(base_dir),
    ]


def delete_task_args(task_name: str = TASK_NAME) -> list:
    return ["schtasks", "/delete", "/tn", task_name, "/f"]


def query_task_args(task_name: str = TASK_NAME) -> list:
    return ["schtasks", "/query", "/tn", task_name]


def scheduler_available() -> bool:
    return runtime.IS_WINDOWS and shutil.which("schtasks") is not None


def run_schtasks(args: list) -> tuple:
    """(成功したか, 表示するメッセージ)"""
    if not scheduler_available():
        return False, "タスクスケジューラは Windows でのみ使えます。"
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"実行できませんでした: {e}"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()
