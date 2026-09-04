"""Google カレンダーへのつなぎ方を判定する・つなぐ

つなぎ方は3通りある。

1. Google でログイン（OAuth）      … 友人向け。ボタン1つ。事前準備なし
2. ICS ファイル                     … Google の設定が一切要らない
3. サービスアカウント               … 完全無人で回したい人向け。設定が重い

このモジュールは google 系ライブラリを **モジュールの先頭では import しない**。
ICS 方式しか使わない人に重い依存を強いないため、必要になった関数の中でだけ読む。

なぜ OAuth を「共有アプリ」方式にするのか
------------------------------------------
Google Cloud でのプロジェクト作成・サービスアカウント発行・カレンダー共有は
20分ほどかかり、人に勧めるときはここで確実に脱落する。OAuth クライアントを
作る側（配る人）が1回だけ用意して同梱すれば、受け取る側の作業は
「Google でログイン」の1回だけになる。

なお OAuth 同意画面は「本番」に公開しておくこと。「テスト」のままだと
リフレッシュトークンが7日で失効し、ある日静かに止まる。未確認のまま
公開した場合は利用者100人までで、初回に「このアプリは確認されていません」
という警告が出る（配る相手にはその旨を伝えておく）。
"""
import json
import os
from dataclasses import dataclass

OAUTH_CLIENT_FILE = "oauth_client.json"
TOKEN_FILE = "token.json"
SERVICE_ACCOUNT_FILE = "service_account.json"

# 予定の読み書きだけができれば足りる。カレンダーの作成や削除の権限は要らない
OAUTH_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
# サービスアカウント方式は、共有されたカレンダーの存在確認もするので広めに取る
SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/calendar"]


@dataclass
class Status:
    """今どうつながっているか（画面にそのまま出せる形）"""
    method: str          # "oauth" / "service_account" / "none"
    ok: bool
    title: str
    detail: str = ""
    account: str = ""

    @property
    def connected(self) -> bool:
        return self.ok and self.method != "none"


def paths(base_dir: str, config: dict | None = None) -> dict:
    """認証に使うファイルの場所をまとめて返す"""
    config = config or {}

    def resolve(key: str, default: str) -> str:
        value = config.get(key) or default
        return value if os.path.isabs(value) else os.path.join(base_dir, value)

    return {
        "oauth_client": resolve("oauth_client_file", OAUTH_CLIENT_FILE),
        "token": resolve("token_file", TOKEN_FILE),
        "service_account": resolve("service_account_file", SERVICE_ACCOUNT_FILE),
    }


def has_oauth_client(base_dir: str, config: dict | None = None) -> bool:
    """配布物に OAuth クライアントが同梱されているか"""
    path = paths(base_dir, config)["oauth_client"]
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    body = data.get("installed") or data.get("web") or {}
    client_id = body.get("client_id", "")
    # 雛形のまま（プレースホルダ）なら未設定とみなす
    return bool(client_id) and "ここに" not in client_id and "YOUR_" not in client_id


def status(base_dir: str, config: dict | None = None) -> Status:
    """ネットワークを使わずに、今の接続状態を判定する"""
    p = paths(base_dir, config)

    if os.path.isfile(p["service_account"]):
        return Status("service_account", True, "サービスアカウントで接続します",
                      "service_account.json が置かれています。")

    if os.path.isfile(p["token"]):
        return Status("oauth", True, "Google アカウントに接続済み",
                      "このまま予定を登録できます。\n"
                      "別のアカウントに変えたいときは、もう一度ログインしてください。")

    if has_oauth_client(base_dir, config):
        return Status("none", False, "まだ Google に接続していません",
                      "「Google でログイン」を押すと、ブラウザが開きます。\n"
                      "許可すると、以後は自動でカレンダーに登録されます。")

    return Status("none", False, "Google への接続手段がありません",
                  "配布物に oauth_client.json が含まれていません。\n"
                  "ICS ファイル方式（Google の設定が不要）を使うか、\n"
                  "README の「サービスアカウント方式」を設定してください。")


def _save_token(path: str, creds) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def connect(base_dir: str, config: dict | None = None) -> Status:
    """ブラウザを開いて Google にログインし、その許可を保存する

    ここだけが対話的。定期実行のときにブラウザが開いては困るので、
    load_credentials() からは絶対に呼ばない。
    """
    p = paths(base_dir, config)
    if not has_oauth_client(base_dir, config):
        return status(base_dir, config)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return Status("none", False, "Google API 用のライブラリが入っていません",
                      "setup_google.bat を実行してください。")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(p["oauth_client"], OAUTH_SCOPES)
        creds = flow.run_local_server(
            port=0,
            prompt="consent",   # 毎回リフレッシュトークンを受け取るため
            authorization_prompt_message="ブラウザで Google にログインしてください…",
            success_message="接続できました。このタブを閉じて、アプリに戻ってください。",
        )
    except Exception as e:
        return Status("none", False, "ログインを完了できませんでした", _short(e))

    _save_token(p["token"], creds)

    account = ""
    try:
        account = probe_account(creds)
    except Exception:
        pass   # 保存は成功しているので、表示名が取れなくても止めない

    return Status("oauth", True, "Google アカウントに接続しました",
                  "以後は自動でカレンダーに登録されます。", account)


def probe_account(creds) -> str:
    """つながっている先のカレンダー名（多くの場合はメールアドレス）を取る

    接続確認も兼ねる。events().list は calendar.events スコープで呼べる。
    """
    from googleapiclient.discovery import build

    service = build("calendar", "v3", credentials=creds)
    result = service.events().list(calendarId="primary", maxResults=1).execute()
    return result.get("summary", "")


def load_credentials(base_dir: str, config: dict | None = None):
    """保存済みの許可を読み込む（必要なら更新する）。ブラウザは開かない"""
    p = paths(base_dir, config)
    # ライブラリを読む前に、まず「ログインしたかどうか」を見る。
    # 未ログインのときは、それが一番役に立つ案内なので
    if not os.path.isfile(p["token"]):
        raise FileNotFoundError(
            "Google に接続していません。\n"
            "  設定画面の「Google でログイン」、または\n"
            "      python main.py --connect-google\n"
            "  を実行してください。"
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    try:
        creds = Credentials.from_authorized_user_file(p["token"], OAUTH_SCOPES)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(
            f"{p['token']} を読めませんでした（{e}）。\n"
            "  古い形式の可能性があります。もう一度ログインしてください:\n"
            "      python main.py --connect-google"
        ) from e

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(p["token"], creds)
        else:
            raise ValueError(
                "Google の許可が切れています。もう一度ログインしてください:\n"
                "      python main.py --connect-google"
            )
    return creds


def _short(e: Exception) -> str:
    text = str(e)
    return text if len(text) <= 300 else text[:300] + "..."
