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
import logging  # noqa: E402
import os  # noqa: E402
from datetime import date  # noqa: E402

import yaml  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# calendar_client は google 系ライブラリを読み込むので、ここでは import しない。
# --list-sites / --dry-run は Google の認証情報が無くても動くようにしたい。
from engine import runtime  # noqa: E402
from engine.site_config import SiteConfigError, load_site_configs  # noqa: E402

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


def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(BASE_DIR, "config.yaml")
    if not os.path.exists(path):
        copy_cmd = ("copy config.example.yaml config.yaml" if runtime.IS_WINDOWS
                    else "cp config.example.yaml config.yaml")
        raise SystemExit(
            f"{path} がありません。config.example.yaml をコピーして作成してください:\n"
            f"    {copy_cmd}"
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
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.get("headless", True))
        context = await browser.new_context(
            user_agent=settings.get("user_agent") or runtime.default_user_agent()
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


async def main_async(args):
    config = load_config(args.config)
    settings = config.get("settings", {})
    calendar_config = config.get("google_calendar", {})

    sites = load_site_configs(os.path.join(BASE_DIR, "sites"))

    if args.list_sites:
        for s in sites:
            state = "有効" if s.enabled else "無効"
            output(f"  {s.slug:<24} {s.name:<24} [{state}] 一覧 {len(s.listings)} ページ")
        return 0

    targets = [s for s in sites if (s.slug in args.site) or (not args.site and s.enabled)]
    if not targets:
        logger.error("実行対象のサイトがありません（--list-sites で確認してください）")
        return 1

    cal = None
    if not args.dry_run:
        from engine.calendar_client import CalendarClient

        cal = CalendarClient(calendar_config, base_dir=BASE_DIR)
        cal.authenticate()

    all_entries = []
    for site in targets:
        logger.info(f"=== {site.name} 開始 ===")
        all_entries.extend(await run_site(site, settings))

    logger.info(f"合計 {len(all_entries)} 件の締切を検出")
    if not all_entries:
        return 0

    if args.dry_run:
        for e in sorted(all_entries, key=lambda x: x.deadline):
            output(f"  {e.deadline}  [{e.source}] {e.company} / {e.event_title}")
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
