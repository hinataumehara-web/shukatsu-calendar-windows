#!/usr/bin/env python3
"""就活サイトのエントリー締切を Google Calendar に自動登録する

使い方（Windows）:
    .venv\\Scripts\\python.exe main.py                  # 有効な全サイトを巡回して同期
    .venv\\Scripts\\python.exe main.py --dry-run        # 書き込まず、検出結果だけ表示
    .venv\\Scripts\\python.exe main.py --site type_shukatsu
    .venv\\Scripts\\python.exe main.py --list-sites

使い方（mac / Linux）:
    .venv/bin/python main.py --dry-run
"""
import sys

# ---- 以降のコードは新しい型注釈の記法を使うので、先にバージョンを確認する ----
# （3.9 以下だと関数定義の時点で TypeError になり、原因が分からない）
if sys.version_info < (3, 10):
    sys.exit(
        "Python 3.10 以上が必要です（今使われているのは "
        + ".".join(str(n) for n in sys.version_info[:3])
        + "）。\npython.org から新しい Python を入れ直してください。\n"
        + "使われている実行ファイル: " + sys.executable
    )

import argparse  # noqa: E402
import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from datetime import date  # noqa: E402

import yaml  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# calendar_client は google 系ライブラリを読み込むので、ここでは import しない。
# --list-sites / --dry-run は Google の認証情報が無くても動くようにしたい。
from engine import google_setup, ics, runtime, session  # noqa: E402
from engine.site_config import (  # noqa: E402
    SiteConfigError,
    build_variables,
    load_site_configs,
    suggest_grad_year,
)

logger = logging.getLogger("shukatsu")


def setup_logging(log_file: str | None):
    handlers: list[logging.Handler] = []

    # pythonw.exe（コンソール無し実行）では sys.stdout が None になる
    if runtime.has_console():
        handlers.append(logging.StreamHandler(sys.stdout))

    if log_file:
        # encoding を指定しないと Windows では cp932 で書かれ、
        # 企業名に含まれる絵文字などで UnicodeEncodeError になる
        handlers.append(logging.FileHandler(
            os.path.join(BASE_DIR, log_file), encoding="utf-8"
        ))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def output(text: str):
    """コンソールが無い環境でも落ちない print"""
    if runtime.has_console():
        print(text)
    else:
        logger.info(text)


def load_config(path: str | None = None, required: bool = True) -> dict:
    path = path or os.path.join(BASE_DIR, "config.yaml")
    if not os.path.exists(path):
        if not required:
            # ICS 方式なら config.yaml が無くても既定値で動く
            return {}
        copy_cmd = ("copy config.example.yaml config.yaml" if runtime.IS_WINDOWS
                    else "cp config.example.yaml config.yaml")
        raise SystemExit(
            f"{path} がありません。config.example.yaml をコピーして作成してください:\n"
            f"    {copy_cmd}\n"
            "\n"
            "なお、Google カレンダーの設定をせずに使うこともできます。\n"
            "その場合 config.yaml は不要です:\n"
            "    " + ("ics.bat" if runtime.IS_WINDOWS else "python main.py --ics")
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dotenv(path: str | None = None):
    """依存を増やさないための最小限の .env ローダ（既存の環境変数を優先）"""
    path = path or os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    # BOM 付きで保存されがち（Windows のメモ帳・PowerShell の既定）なので
    # utf-8-sig で読む。BOM が無い普通の UTF-8 もそのまま読める。
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def run_site(site, settings: dict):
    """1サイトを巡回して締切リストを返す"""
    from playwright.async_api import async_playwright

    from engine.scraper import GenericScraper

    entries = []
    # login.mode: manual のサイトは、--login で保存したログイン状態を読み込む
    storage_state = session.load_path(BASE_DIR, site.slug) if site.uses_saved_session() else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.get("headless", True))
        context = await browser.new_context(
            user_agent=settings.get("user_agent") or runtime.default_user_agent(),
            storage_state=storage_state,
        )
        page = await context.new_page()
        scraper = GenericScraper(site, page, settings, base_dir=BASE_DIR)
        try:
            await scraper.login()
            found = await scraper.collect()
            days_ahead = settings.get("days_ahead", 90)
            today = date.today()
            entries = [
                e for e in found
                if today <= e.deadline and (e.deadline - today).days <= days_ahead
            ]
            logger.info(f"{site.name}: 期間内 {len(entries)} 件 / 検出 {len(found)} 件")
        except Exception as e:
            logger.error(f"{site.name}: 処理中にエラー: {e}", exc_info=True)
        finally:
            await browser.close()
    return entries


async def login_site(site, settings: dict):
    """ブラウザを開いて人にログインしてもらい、その状態を保存する

    マイナビの6桁確認コードやリクナビの JavaScript 製ログイン画面は
    YAML の手順では越えられない。1回だけ手でログインし、Cookie を保存して
    以後の巡回で使い回す。
    """
    from playwright.async_api import async_playwright

    if not runtime.has_console():
        logger.error("--login は対話が必要です。コンソールのある状態で実行してください。")
        return 1

    start_url = site.login_url or (site.listings[0].url if site.listings else "")
    if not start_url:
        logger.error(f"{site.name}: login.url も listings も無いため開く先が決まりません")
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=settings.get("user_agent") or runtime.default_user_agent()
        )
        page = await context.new_page()
        await page.goto(start_url, wait_until="domcontentloaded")

        output("")
        output(f"  ブラウザで「{site.name}」にログインしてください。")
        output("  2段階認証のコード入力まで終わらせ、マイページが表示された状態にします。")
        output("  終わったら、この画面で Enter を押してください。")
        output("")
        await asyncio.get_running_loop().run_in_executor(None, input, "  Enter で保存 > ")

        state = await context.storage_state()
        path = session.save(BASE_DIR, site.slug, state)

        # 保存した状態で本当に見えるか、一覧ページで軽く確認する
        if site.listings:
            await page.goto(site.listings[0].url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            marker = site.login_success_url_not_contains
            if marker and marker in page.url:
                output(f"  警告: 一覧ページが {page.url} に飛ばされました。")
                output("  ログインが完了していない可能性があります。")
        await browser.close()

    output(f"  ログイン状態を保存しました: {path}")
    output(f"  確認: python main.py --site {site.slug} --dry-run")
    logger.info(f"{site.name}: セッションを保存しました")
    return 0


def write_ics(entries, path_arg: str, calendar_config: dict) -> int:
    """締切を .ics に書き出し、取り込み方を案内する"""
    path = path_arg if os.path.isabs(path_arg) else os.path.join(BASE_DIR, path_arg)
    ics.write(
        path, entries,
        event_tag=calendar_config.get("event_tag", "[就活自動登録]"),
        reminder_days=calendar_config.get("reminder_days", [3, 1]),
        calendar_name=calendar_config.get("calendar_name", "就活の締切"),
    )
    logger.info(f"{len(entries)} 件を {path} に書き出しました")
    output("")
    output(f"  {path} を作りました。カレンダーに取り込んでください。")
    output("")
    output("  Google カレンダー:")
    output("    https://calendar.google.com/calendar/u/0/r/settings/export")
    output("    →「インポート」でこのファイルを選ぶ")
    output("")
    output("  同じ締切は同じ ID を持たせてあるので、毎日取り込み直しても重複しません。")
    return 0


def connect_google(calendar_config: dict) -> int:
    """ブラウザを開いて Google にログインし、許可を保存する"""
    before = google_setup.status(BASE_DIR, calendar_config)
    if before.method == "service_account":
        output("  すでにサービスアカウントで接続する設定になっています。")
        output("  Google アカウントでのログインに切り替えるなら、")
        output("  service_account.json を別の場所に移してから実行してください。")
        return 0

    output("")
    output("  ブラウザが開きます。カレンダーに登録したい Google アカウントを選び、")
    output("  アクセスを許可してください。")
    output("")

    result = google_setup.connect(BASE_DIR, calendar_config)
    output(f"  {result.title}")
    if result.account:
        output(f"  接続先: {result.account}")
    if result.detail:
        for line in result.detail.splitlines():
            output(f"  {line}")

    if result.ok:
        logger.info(f"Google に接続しました（{result.account or '接続先不明'}）")
        return 0
    logger.error(f"Google への接続に失敗: {result.title}")
    return 1


async def main_async(args):
    config = load_config(args.config, required=not (args.ics or args.connect_google))
    settings = config.get("settings", {})
    calendar_config = config.get("google_calendar", {})

    if args.connect_google:
        return connect_google(calendar_config)

    variables = build_variables(config)
    sites = load_site_configs(os.path.join(BASE_DIR, "sites"), variables)

    if args.list_sites:
        for s in sites:
            state = "有効" if s.enabled else "無効"
            auth = f"手動ログイン: {session.describe(BASE_DIR, s.slug)}" if s.uses_saved_session() else "自動ログイン"
            todo = s.unresolved_variables()
            note = f" / 要設定: {', '.join(todo)}" if todo else ""
            output(f"  {s.slug:<20} {s.name:<22} [{state}] 一覧 {len(s.listings)} / {auth}{note}")
        return 0

    if args.login:
        target = next((s for s in sites if s.slug == args.login), None)
        if target is None:
            logger.error(f"サイト定義が見つかりません: {args.login}")
            return 1
        return await login_site(target, settings)

    targets = [s for s in sites if (s.slug in args.site) or (not args.site and s.enabled)]
    if not targets:
        logger.error("実行対象のサイトがありません（--list-sites で確認してください）")
        return 1

    unset = [s for s in targets if s.unresolved_variables()]
    for s in unset:
        names = "、".join(s.unresolved_variables())
        logger.error(
            f"{s.name}: URL に埋める値（{names}）が決まっていません。\n"
            f"  config.yaml の settings.grad_year に卒業予定年を入れてください"
            f"（例: grad_year: {suggest_grad_year()}）。\n"
            f"  設定画面（setup_gui.bat）の「卒業予定年」からも設定できます。"
        )
    targets = [s for s in targets if s not in unset]
    if not targets:
        return 1

    missing = [s for s in targets if s.uses_saved_session() and not session.exists(BASE_DIR, s.slug)]
    for s in missing:
        logger.error(
            f"{s.name}: ログイン状態が保存されていません。先に実行してください: "
            f"python main.py --login {s.slug}"
        )
    targets = [s for s in targets if s not in missing]
    if not targets:
        return 1

    cal = None
    if not args.dry_run and not args.ics:
        try:
            from engine.calendar_client import CalendarClient
        except ImportError as e:
            logger.error(
                f"Google カレンダー API 用のライブラリが入っていません（{e}）。\n"
                "  この方式を使うなら setup_google.bat を実行してください。\n"
                "  Google の設定をしたくない場合は、代わりに ICS 方式が使えます:\n"
                "      run.bat --ics        （または ics.bat をダブルクリック）"
            )
            return 1

        cal = CalendarClient(calendar_config, base_dir=BASE_DIR)
        cal.authenticate()

    all_entries = []
    for site in targets:
        logger.info(f"=== {site.name} 開始 ===")
        all_entries.extend(await run_site(site, settings))

    logger.info(f"合計 {len(all_entries)} 件の締切を検出")
    if not all_entries:
        return 0

    if args.dry_run or args.ics:
        for e in sorted(all_entries, key=lambda x: x.deadline):
            output(f"  {e.deadline}  [{e.source}] {e.company} / {e.event_title}")

    if args.ics:
        return write_ics(all_entries, args.ics, calendar_config)

    if args.dry_run:
        logger.info("dry-run のためカレンダーには書き込みませんでした")
        return 0

    added, skipped = cal.sync(all_entries, settings.get("days_ahead", 90))
    logger.info(f"同期完了: {added} 件追加, {skipped} 件スキップ（重複）")
    return 0


def main():
    runtime.setup()

    parser = argparse.ArgumentParser(description="就活サイトの締切を Google Calendar に同期する")
    parser.add_argument("--config", help="設定ファイルのパス（既定: config.yaml）")
    parser.add_argument("--site", action="append", default=[],
                        help="実行するサイトの slug（sites/<slug>.yaml）。複数指定可")
    parser.add_argument("--dry-run", action="store_true",
                        help="カレンダーに書き込まず、検出した締切を表示するだけ")
    parser.add_argument("--list-sites", action="store_true", help="サイト定義の一覧を表示")
    parser.add_argument("--connect-google", action="store_true",
                        help="ブラウザを開いて Google にログインし、"
                             "カレンダーへの登録を許可する（初回だけ）")
    parser.add_argument("--ics", nargs="?", const="shukatsu.ics", metavar="PATH",
                        help="Google API を使わず、締切を .ics ファイルに書き出す"
                             "（既定: shukatsu.ics）")
    parser.add_argument("--login", metavar="SLUG",
                        help="ブラウザを開いて手動ログインし、その状態を保存する"
                             "（login.mode: manual のサイト用）")
    args = parser.parse_args()

    load_dotenv()
    config_for_log = {}
    try:
        config_for_log = load_config(args.config)
    except SystemExit:
        pass
    setup_logging(config_for_log.get("settings", {}).get("log_file", "shukatsu.log"))

    try:
        return runtime.run(main_async(args))
    except SiteConfigError as e:
        logger.error(f"サイト定義エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
