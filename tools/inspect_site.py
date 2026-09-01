#!/usr/bin/env python3
"""サイト定義を作る・直すための調査ツール

一覧ページのテキストを行番号つきで書き出す。
「締切」を示す行がどんな形か、企業名が何行前に出るかを確認して
sites/<slug>.yaml の deadline / company を調整するために使う。

使い方（Windows）:
    .venv\\Scripts\\python.exe tools\\inspect_site.py type_shukatsu
    .venv\\Scripts\\python.exe tools\\inspect_site.py type_shukatsu --no-login
    .venv\\Scripts\\python.exe tools\\inspect_site.py type_shukatsu --grep 締切
    .venv\\Scripts\\python.exe tools\\inspect_site.py type_shukatsu --headed
"""
import sys

if sys.version_info < (3, 10):
    sys.exit(
        "Python 3.10 以上が必要です（今使われているのは "
        + ".".join(str(n) for n in sys.version_info[:3]) + "）。"
    )

import argparse  # noqa: E402
import os  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from engine import runtime  # noqa: E402
from engine.site_config import load_site_configs  # noqa: E402


async def inspect(slug: str, listing_index: int, no_login: bool, grep: str | None, headed: bool):
    from playwright.async_api import async_playwright

    from engine.scraper import GenericScraper

    sites = {s.slug: s for s in load_site_configs(os.path.join(BASE_DIR, "sites"))}
    if slug not in sites:
        print(f"サイト定義が見つかりません: {slug}")
        print(f"利用可能: {', '.join(sorted(sites))}")
        return 1
    site = sites[slug]
    listing = site.listings[listing_index]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context(user_agent=runtime.default_user_agent())
        page = await context.new_page()
        scraper = GenericScraper(site, page, {"debug_screenshots": False}, base_dir=BASE_DIR)
        try:
            if not no_login:
                await scraper.login()
            await page.goto(listing.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(listing.wait_ms)
            text = await page.inner_text("body")
        finally:
            await browser.close()

    lines = [l.strip() for l in text.split("\n")]
    if listing.drop_empty_lines:
        lines = [l for l in lines if l]

    out_path = os.path.join(BASE_DIR, f"inspect_{slug}.txt")
    # encoding を明示しないと Windows では cp932 で書かれ、
    # ページ中の絵文字などで UnicodeEncodeError になる
    with open(out_path, "w", encoding="utf-8") as f:
        for i, line in enumerate(lines):
            f.write(f"{i:5d}  {line}\n")

    print(f"{len(lines)} 行を {out_path} に書き出しました")
    if grep:
        print(f"--- '{grep}' を含む行 ---")
        for i, line in enumerate(lines):
            if grep in line:
                print(f"{i:5d}  {line}")
    return 0


def main():
    runtime.setup()

    ap = argparse.ArgumentParser(description="一覧ページのテキストを調べる")
    ap.add_argument("slug", help="sites/<slug>.yaml の slug")
    ap.add_argument("--listing", type=int, default=0, help="listings の何番目か（既定: 0）")
    ap.add_argument("--no-login", action="store_true", help="ログインを行わない")
    ap.add_argument("--grep", help="この文字列を含む行だけ標準出力に表示")
    ap.add_argument("--headed", action="store_true", help="ブラウザを画面に表示する")
    args = ap.parse_args()

    # .env を読む（メモ帳などが付ける BOM も許容する）
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    return runtime.run(inspect(args.slug, args.listing, args.no_login, args.grep, args.headed))


if __name__ == "__main__":
    sys.exit(main())
