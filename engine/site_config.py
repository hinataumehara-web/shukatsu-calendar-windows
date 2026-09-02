"""サイト定義 YAML の読み込みとバリデーション

Python を書かずに YAML だけで対応サイトを増やせるようにするための層。
スキーマの説明は sites/example_site.yaml を参照。
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

VALID_ACTIONS = {"goto", "click", "fill", "type", "press", "wait", "select"}
# steps  : YAML に書いた手順で自動ログインする（従来方式）
# manual : 最初の1回だけ人がブラウザでログインし、その状態を保存して使い回す
#          （2段階認証や JavaScript 製ログイン画面のサイト向け）
VALID_LOGIN_MODES = {"steps", "manual"}
VALID_MATCH_MODES = {"exact", "regex", "keyword"}
VALID_DATE_SOURCES = {"same_line", "next_line", "context"}


class SiteConfigError(ValueError):
    """サイト定義が不正なときに送出される"""


@dataclass
class CompanyRule:
    """締切行の手前を遡って会社名・タイトルを拾うためのルール"""
    lookback: int = 8
    min_length: int = 4
    skip_exact: list[str] = field(default_factory=list)
    skip_patterns: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._compiled = [re.compile(p) for p in self.skip_patterns]
        self._skip_exact = set(self.skip_exact)

    def is_noise(self, line: str) -> bool:
        if not line or len(line) < self.min_length:
            return True
        if line in self._skip_exact:
            return True
        return any(p.search(line) for p in self._compiled)


@dataclass
class DeadlineRule:
    """どの行を「締切行」とみなし、どこから日付を読むか"""
    match: str = "keyword"
    value: Optional[str] = None          # exact / regex のときのパターン
    keywords: list[str] = field(default_factory=list)  # keyword のとき（空なら既定値）
    date_from: str = "same_line"
    context_before: int = 1
    context_after: int = 3

    def __post_init__(self):
        if self.match not in VALID_MATCH_MODES:
            raise SiteConfigError(f"deadline.match は {VALID_MATCH_MODES} のいずれか: {self.match!r}")
        if self.date_from not in VALID_DATE_SOURCES:
            raise SiteConfigError(f"deadline.date_from は {VALID_DATE_SOURCES} のいずれか: {self.date_from!r}")
        if self.match in ("exact", "regex") and not self.value:
            raise SiteConfigError(f"deadline.match: {self.match} には value が必要です")
        self._regex = re.compile(self.value) if self.match == "regex" else None

    def matches(self, line: str) -> bool:
        if self.match == "exact":
            return line == self.value
        if self.match == "regex":
            return bool(self._regex.search(line))
        from .dateparse import has_deadline_keyword
        return has_deadline_keyword(line, self.keywords or None)


@dataclass
class Listing:
    """1つの一覧ページ"""
    url: str
    wait_ms: int = 3000
    title_prefix: str = ""
    drop_empty_lines: bool = True
    dedupe: bool = True
    skip_if_context_contains: list[str] = field(default_factory=list)
    deadline: DeadlineRule = field(default_factory=DeadlineRule)
    company: CompanyRule = field(default_factory=CompanyRule)


@dataclass
class SiteConfig:
    """1サイト分の定義"""
    name: str
    login_url: str
    login_steps: list[dict[str, Any]]
    listings: list[Listing]
    slug: str = ""
    enabled: bool = True
    email_env: str = ""
    password_env: str = ""
    login_mode: str = "steps"
    login_success_url_not_contains: str = ""
    login_success_selector: str = ""
    logged_out_marker: str = ""

    # --- 認証情報は環境変数からのみ読む（YAML には決して書かない） ---
    def credentials(self) -> dict[str, str]:
        creds = {}
        for label, var in (("email", self.email_env), ("password", self.password_env)):
            if not var:
                continue
            value = os.environ.get(var)
            if not value:
                raise SiteConfigError(
                    f"[{self.name}] 環境変数 {var} が設定されていません。\n"
                    f".env ファイル（.env.example をコピー）に {var}=... を書いてください。"
                )
            creds[label] = value
        return creds

    def requires_login(self) -> bool:
        if self.login_mode == "manual":
            return True
        return bool(self.login_url and self.login_steps)

    def uses_saved_session(self) -> bool:
        """保存済みセッションを使う（自動ログインを行わない）方式か"""
        return self.login_mode == "manual"


def _validate_steps(name: str, steps: list) -> list[dict]:
    out = []
    for i, step in enumerate(steps or []):
        if not isinstance(step, dict) or "action" not in step:
            raise SiteConfigError(f"[{name}] login.steps[{i}] に action がありません")
        action = step["action"]
        if action not in VALID_ACTIONS:
            raise SiteConfigError(
                f"[{name}] login.steps[{i}] の action が不正です: {action!r}（有効: {sorted(VALID_ACTIONS)}）"
            )
        if action in ("click", "fill", "type", "press", "select") and not step.get("selector"):
            raise SiteConfigError(f"[{name}] login.steps[{i}] ({action}) には selector が必要です")
        if action == "press" and not step.get("key"):
            raise SiteConfigError(f"[{name}] login.steps[{i}] (press) には key が必要です")
        out.append(step)
    return out


def parse_site_config(raw: dict, slug: str = "") -> SiteConfig:
    if not isinstance(raw, dict):
        raise SiteConfigError(f"[{slug}] YAML のトップレベルはマッピングである必要があります")

    name = raw.get("name") or slug
    if not name:
        raise SiteConfigError(f"[{slug}] name がありません")

    login = raw.get("login") or {}
    creds = raw.get("credentials") or {}

    login_mode = login.get("mode", "steps")
    if login_mode not in VALID_LOGIN_MODES:
        raise SiteConfigError(
            f"[{name}] login.mode は {sorted(VALID_LOGIN_MODES)} のいずれか: {login_mode!r}"
        )

    success_check = login.get("success_check") or {}

    listings_raw = raw.get("listings")
    if not listings_raw:
        raise SiteConfigError(f"[{name}] listings が空です（最低1つの一覧ページが必要）")

    listings = []
    for i, item in enumerate(listings_raw):
        if not item.get("url"):
            raise SiteConfigError(f"[{name}] listings[{i}] に url がありません")
        deadline = DeadlineRule(**(item.get("deadline") or {}))
        company = CompanyRule(**(item.get("company") or {}))
        listings.append(Listing(
            url=item["url"],
            wait_ms=int(item.get("wait_ms", 3000)),
            title_prefix=item.get("title_prefix", ""),
            drop_empty_lines=bool(item.get("drop_empty_lines", True)),
            dedupe=bool(item.get("dedupe", True)),
            skip_if_context_contains=item.get("skip_if_context_contains") or [],
            deadline=deadline,
            company=company,
        ))

    for key in ("email", "password"):
        if key in creds:
            raise SiteConfigError(
                f"[{name}] credentials.{key} に値を直接書くことはできません。\n"
                f"credentials.{key}_env に環境変数名を書き、値は .env に置いてください。"
            )

    return SiteConfig(
        name=name,
        slug=slug or name,
        enabled=bool(raw.get("enabled", True)),
        email_env=creds.get("email_env", ""),
        password_env=creds.get("password_env", ""),
        login_mode=login_mode,
        login_url=login.get("url", ""),
        login_steps=_validate_steps(name, login.get("steps")),
        login_success_url_not_contains=success_check.get("url_not_contains", ""),
        login_success_selector=success_check.get("selector", ""),
        logged_out_marker=success_check.get("logged_out_text", ""),
        listings=listings,
    )


def load_site_configs(sites_dir: str | Path) -> list[SiteConfig]:
    """sites/*.yaml をすべて読み込む（ファイル名順）"""
    sites_dir = Path(sites_dir)
    if not sites_dir.is_dir():
        raise SiteConfigError(f"サイト定義ディレクトリが見つかりません: {sites_dir}")

    configs = []
    for path in sorted(sites_dir.glob("*.y*ml")):
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            continue
        configs.append(parse_site_config(raw, slug=path.stem))
    return configs
