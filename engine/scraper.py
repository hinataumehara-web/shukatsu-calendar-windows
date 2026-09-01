"""サイト定義（YAML）どおりに動く汎用スクレイパー

サイトごとに Python を書く代わりに、sites/*.yaml の指示を解釈して
「ログイン → 一覧ページのテキスト取得 → 締切行の抽出」を行う。
"""
import logging
import os
from typing import Optional

from playwright.async_api import Page

from .dateparse import parse_date
from .models import DeadlineEntry
from .site_config import Listing, SiteConfig

logger = logging.getLogger(__name__)


class GenericScraper:
    def __init__(self, site: SiteConfig, page: Page, settings: dict, base_dir: str = "."):
        self.site = site
        self.page = page
        self.settings = settings or {}
        self.debug = self.settings.get("debug_screenshots", False)
        # スクショの保存先はカレントディレクトリではなくリポジトリ直下に固定する。
        # Windows のタスクスケジューラは作業ディレクトリが C:\Windows\System32 に
        # なることがあり、相対パスだと書き込めずに失敗する。
        self.base_dir = base_dir

    # ------------------------------------------------------------------ utils
    async def _screenshot(self, name: str):
        if not self.debug:
            return
        path = os.path.join(self.base_dir, f"debug_{self.site.slug}_{name}.png")
        try:
            await self.page.screenshot(path=path)
            logger.debug(f"スクリーンショット保存: {path}")
        except Exception as e:  # スクショ失敗で本処理を止めない
            logger.debug(f"スクリーンショット失敗: {e}")

    # ------------------------------------------------------------------ login
    async def login(self):
        if not self.site.requires_login():
            logger.info(f"{self.site.name}: ログイン不要の定義です")
            return

        creds = self.site.credentials()
        logger.info(f"{self.site.name}: ログイン中...")
        await self.page.goto(self.site.login_url, wait_until="domcontentloaded")
        await self._screenshot("login_before")

        for step in self.site.login_steps:
            await self._run_step(step, creds)

        await self.page.wait_for_load_state("domcontentloaded")
        await self._screenshot("login_after")

        marker = self.site.login_success_url_not_contains
        if marker and marker in self.page.url:
            raise RuntimeError(
                f"{self.site.name}: ログインに失敗した可能性があります"
                f"（URL が {self.page.url} のままです）。"
                "認証情報とセレクタを確認してください。"
            )
        logger.info(f"{self.site.name}: ログイン完了")

    async def _run_step(self, step: dict, creds: dict):
        action = step["action"]
        selector = step.get("selector")
        value = self._render(step.get("value", ""), creds)
        delay = step.get("delay_ms")

        if action == "goto":
            await self.page.goto(self._render(step["url"], creds), wait_until="domcontentloaded")
        elif action == "click":
            await self.page.click(selector)
        elif action == "fill":
            await self.page.fill(selector, value)
        elif action == "type":
            await self.page.type(selector, value, delay=delay or 0)
        elif action == "press":
            await self.page.press(selector, step["key"])
        elif action == "select":
            await self.page.select_option(selector, value)
        elif action == "wait":
            await self.page.wait_for_timeout(int(step.get("ms", 1000)))

        if action != "wait" and step.get("then_wait_ms"):
            await self.page.wait_for_timeout(int(step["then_wait_ms"]))

    @staticmethod
    def _render(template: str, creds: dict) -> str:
        """{email} / {password} を実際の値に置き換える"""
        if not isinstance(template, str):
            return template
        out = template
        for key, val in creds.items():
            out = out.replace("{" + key + "}", val)
        return out

    # --------------------------------------------------------------- scraping
    async def collect(self) -> list[DeadlineEntry]:
        entries: list[DeadlineEntry] = []
        for listing in self.site.listings:
            entries.extend(await self._scrape_listing(listing))
        return entries

    async def _scrape_listing(self, listing: Listing) -> list[DeadlineEntry]:
        entries: list[DeadlineEntry] = []
        logger.info(f"{self.site.name}: {listing.url} を取得中...")
        try:
            await self.page.goto(listing.url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(listing.wait_ms)
            await self._screenshot("listing")

            text = await self.page.inner_text("body")
            lines = [l.strip() for l in text.split("\n")]
            if listing.drop_empty_lines:
                lines = [l for l in lines if l]

            rule = listing.deadline
            seen: set[str] = set()

            for i, line in enumerate(lines):
                if not rule.matches(line):
                    continue

                context = "\n".join(
                    lines[max(0, i - rule.context_before): i + rule.context_after + 1]
                )
                if any(word in context for word in listing.skip_if_context_contains):
                    continue

                date_text = self._date_text(lines, i, rule, context)
                deadline = parse_date(date_text)
                if not deadline:
                    continue

                company, title = self._extract_company_title(lines, i, listing)
                if not company:
                    continue

                if listing.dedupe:
                    key = f"{company}|{deadline}"
                    if key in seen:
                        continue
                    seen.add(key)

                entries.append(DeadlineEntry(
                    company=company,
                    event_title=f"{listing.title_prefix}{title or company}",
                    deadline=deadline,
                    url=listing.url,
                    source=self.site.name,
                    description=f"{company} / {title or ''} / 締切 {deadline}",
                ))

        except Exception as e:
            logger.warning(f"{self.site.name}: {listing.url} の取得でエラー: {e}", exc_info=True)

        logger.info(f"{self.site.name}: {len(entries)} 件抽出")
        return entries

    @staticmethod
    def _date_text(lines: list[str], idx: int, rule, context: str) -> str:
        if rule.date_from == "same_line":
            return lines[idx]
        if rule.date_from == "next_line":
            return lines[idx + 1] if idx + 1 < len(lines) else ""
        return context

    @staticmethod
    def _extract_company_title(lines: list[str], idx: int, listing: Listing):
        """締切行の手前を遡り、ノイズでない行を候補にする。

        一覧カードは「タイトル → 会社名 → 締切」の順に並ぶことが多いので、
        締切に最も近い候補を会社名、その1つ前をタイトルとみなす。
        """
        rule = listing.company
        candidates = [
            l for l in lines[max(0, idx - rule.lookback): idx]
            if not rule.is_noise(l)
        ]
        company = candidates[-1] if candidates else ""
        title = candidates[-2] if len(candidates) >= 2 else ""
        return company, title
