"""Google Calendar クライアント

認証方式は2つ。サービスアカウント方式を推奨する。

- サービスアカウント（推奨）: トークンが失効しないので放置しても止まらない。
  OAuth 同意画面の設定も不要。カレンダーをサービスアカウントに共有するだけ。
- OAuth2 ユーザー認証: 同意画面が「テスト」ステータスのままだと
  リフレッシュトークンが7日で失効し、ある日突然 invalid_grant で止まる。
"""
import logging
import os
import pickle
from datetime import datetime, timedelta, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .models import DeadlineEntry

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
DEFAULT_TAG = "[deadline]"


class CalendarClient:
    def __init__(self, config: dict, base_dir: str = "."):
        self.base_dir = base_dir
        self.calendar_id = config.get("calendar_id", "")
        self.service_account_file = self._resolve(config.get("service_account_file", "service_account.json"))
        self.credentials_file = self._resolve(config.get("credentials_file", "credentials.json"))
        self.token_file = self._resolve(config.get("token_file", "token.json"))
        self.event_tag = config.get("event_tag", DEFAULT_TAG)
        self.color_id = str(config.get("color_id", "11"))
        self.reminder_days = config.get("reminder_days", [3, 1])
        self.service = None

    def _resolve(self, path: str) -> str:
        if not path:
            return path
        return path if os.path.isabs(path) else os.path.join(self.base_dir, path)

    # ---------------------------------------------------------------- 認証
    def authenticate(self):
        if self.service_account_file and os.path.exists(self.service_account_file):
            self._authenticate_service_account()
        else:
            logger.warning(
                f"{self.service_account_file} が見つかりません。OAuth 方式にフォールバックします。"
            )
            self._authenticate_oauth()

    def _authenticate_service_account(self):
        creds = service_account.Credentials.from_service_account_file(
            self.service_account_file, scopes=SCOPES
        )
        sa_email = getattr(creds, "service_account_email", "(unknown)")

        if self.calendar_id in (None, "", "primary"):
            raise ValueError(
                'サービスアカウント方式では calendar_id に "primary" は使えません。\n'
                '"primary" はサービスアカウント自身の（誰にも見えない）カレンダーを指すためです。\n'
                "config.yaml の calendar_id に、自分のカレンダー ID を設定してください。"
            )

        self.service = build("calendar", "v3", credentials=creds)
        try:
            self.service.calendars().get(calendarId=self.calendar_id).execute()
        except Exception as e:
            raise PermissionError(
                f"カレンダー '{self.calendar_id}' にアクセスできません: {e}\n"
                f"Google カレンダーの「設定と共有」で、このカレンダーを\n"
                f"  {sa_email}\n"
                f"に「予定の変更権限」で共有してください。"
            ) from e
        logger.info(f"Google Calendar: サービスアカウントで認証完了 ({sa_email})")

    def _authenticate_oauth(self):
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as e:
                    raise RefreshError(
                        f"{e}\n\n"
                        "OAuth のリフレッシュトークンが失効しています。\n"
                        "OAuth 同意画面が「テスト」ステータスのままだとトークンは7日で失効します。\n"
                        "README の「サービスアカウント方式」への移行を検討してください。"
                    ) from e
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"{self.credentials_file} が見つかりません。README を参照してください。"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_file, "wb") as f:
                pickle.dump(creds, f)

        self.service = build("calendar", "v3", credentials=creds)
        logger.info("Google Calendar: OAuth で認証完了")

    # ------------------------------------------------------------ イベント
    def get_existing_keys(self, days_ahead: int = 180) -> set:
        """既に登録済みのイベントのキー集合を返す"""
        existing = set()
        # utcnow() は Python 3.12 で非推奨。タイムゾーン付きで作る。
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat().replace("+00:00", "Z")
        end = (now_dt + timedelta(days=days_ahead)).isoformat().replace("+00:00", "Z")
        try:
            result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=now, timeMax=end,
                maxResults=2500, singleEvents=True,
                q=self.event_tag,
            ).execute()
            for event in result.get("items", []):
                for line in event.get("description", "").split("\n"):
                    if line.startswith("_key:"):
                        existing.add(line[5:].strip())
        except Exception as e:
            logger.warning(f"既存イベントの取得に失敗: {e}")
        return existing

    def _build_event(self, entry: DeadlineEntry) -> dict:
        deadline_str = entry.deadline.isoformat()
        return {
            "summary": f"{self.event_tag} {entry.company} {entry.event_title}",
            "description": (
                f"出典: {entry.source}\n"
                f"URL: {entry.url}\n"
                f"詳細: {entry.description}\n"
                f"_key:{entry.key()}"
            ),
            "start": {"date": deadline_str},
            "end": {"date": deadline_str},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60 * 24 * int(d)}
                    for d in self.reminder_days
                ],
            },
            "colorId": self.color_id,
        }

    def sync(self, entries: list[DeadlineEntry], days_ahead: int = 90,
             dry_run: bool = False) -> tuple[int, int]:
        """締切をカレンダーへ同期する。(追加数, スキップ数) を返す。"""
        existing = set() if dry_run else self.get_existing_keys(days_ahead)
        added = skipped = 0

        for entry in entries:
            if entry.key() in existing:
                skipped += 1
                continue
            if dry_run:
                logger.info(f"[dry-run] 追加予定: {entry.company} / {entry.event_title} / {entry.deadline}")
                added += 1
                existing.add(entry.key())
                continue
            try:
                self.service.events().insert(
                    calendarId=self.calendar_id, body=self._build_event(entry)
                ).execute()
                logger.info(f"追加: {entry.company} / {entry.event_title} / {entry.deadline}")
                existing.add(entry.key())
                added += 1
            except Exception as e:
                logger.error(f"イベント追加に失敗 ({entry.company}): {e}")
                skipped += 1
        return added, skipped
