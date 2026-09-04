"""サイト定義 YAML の読み込みとバリデーション

Python を書かずに YAML だけで対応サイトを増やせるようにするための層。
スキーマの説明は sites/example_site.yaml を参照。
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

VALID_ACTIONS = {"goto", "click", "fill", "type", "press", "wait", "select"}
# steps  : YAML に書いた手順で自動ログインする（従来方式）
# manual : 最初の1回だけ人がブラウザでログインし、その状態を保存して使い回す
#          （2段階認証や JavaScript 製ログイン画面のサイト向け）
VALID_LOGIN_MODES = {"steps", "manual"}
VALID_MATCH_MODES = {"exact", "regex", "keyword"}
# 会社名をどこから拾うか
#   before … 締切行の手前を遡る（一覧ページ向け。既定）
#   top    … ページ先頭から最初の候補を採る（詳細ページ向け。
#            会社名がページの一番上にあり、締切は下の方にあるため）
VALID_COMPANY_PICKS = {"before", "top"}
VALID_DATE_SOURCES = {"same_line", "next_line", "context"}

# URL に埋め込める変数。マイナビのように卒業年が URL に入るサイトのため、
# サイト定義に年度を直接書かず、config.yaml の設定から埋める
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def suggest_grad_year(today: Optional[date] = None) -> int:
    """卒業予定年の初期候補

    日本の年度は4月始まり。インターンや早期選考を主に見るのは3年生（院1年）で、
    その学年の卒業年は「今の年度 + 2」になる。
    （2026年9月なら2026年度なので 2028）
    """
    today = today or date.today()
    fiscal_year = today.year if today.month >= 4 else today.year - 1
    return fiscal_year + 2


def build_variables(config: dict) -> dict:
    """config.yaml から、サイト定義の URL に埋める値を作る"""
    settings = (config or {}).get("settings", {}) or {}
    grad_year = settings.get("grad_year")
    if not grad_year:
        return {}
    grad_year = int(grad_year)
    return {
        "grad_year": str(grad_year),          # 2028
        "grad_yy": f"{grad_year % 100:02d}",  # 28
    }


def _substitute(text: str, variables: dict) -> str:
    if not text or "{" not in text:
        return text
    return _PLACEHOLDER.sub(
        lambda m: variables.get(m.group(1), m.group(0)), text)


def _unresolved(text: str) -> list:
    return _PLACEHOLDER.findall(text or "")


class SiteConfigError(ValueError):
    """サイト定義が不正なときに送出される"""


@dataclass
class CompanyRule:
    """会社名・タイトルを拾うためのルール"""
    lookback: int = 8
    min_length: int = 4
    pick: str = "before"
    # 「ラベル → 値」の順で並ぶページ（詳細ページに多い）向け。
    # ここに挙げた語の *次の行* は、その値とみなして飛ばす。
    # 「募集人数 / 30名」の 30名 をコース名と誤認しないため。
    # skip_exact と分けてあるのは、「仕事体験」のような見出しの直後には
    # 拾いたい行（コース名）が来るため。値を伴うラベルだけをここに書く
    value_labels: list[str] = field(default_factory=list)
    skip_exact: list[str] = field(default_factory=list)
    skip_patterns: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.pick not in VALID_COMPANY_PICKS:
            raise SiteConfigError(
                f"company.pick は {sorted(VALID_COMPANY_PICKS)} のいずれか: {self.pick!r}")
        self._compiled = [re.compile(p) for p in self.skip_patterns]
        self._skip_exact = set(self.skip_exact)
        self._value_labels = set(self.value_labels)

    def is_value_label(self, line: str) -> bool:
        """この行の次に「値」が来るか"""
        return line in self._value_labels

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
class FollowRule:
    """一覧から各ページへ辿って、そちらで締切を読むための設定

    マイナビのように、一覧には「締切間近」としか書かれておらず、
    実際の日付が各社のコース情報ページにしかない場合に使う。
    """
    link_text: str
    max_pages: int = 30
    delay_ms: int = 1500
    wait_ms: int = 3000
    title_prefix: str = ""
    skip_if_context_contains: list[str] = field(default_factory=list)
    deadline: "DeadlineRule" = None
    company: "CompanyRule" = None

    def __post_init__(self):
        if not self.link_text:
            raise SiteConfigError("follow.link_text は必須です（辿るリンクの文字）")
        if self.max_pages < 1:
            raise SiteConfigError(f"follow.max は1以上: {self.max_pages}")
        self.deadline = self.deadline or DeadlineRule()
        self.company = self.company or CompanyRule()


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
    follow: Optional[FollowRule] = None


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

    def unresolved_variables(self) -> list:
        """URL に残っている、まだ値が決まっていない変数名

        例: config.yaml に settings.grad_year が無いまま
        マイナビの定義を使うと ["grad_yy"] が返る。
        """
        names = set(_unresolved(self.login_url))
        for listing in self.listings:
            names.update(_unresolved(listing.url))
        return sorted(names)

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


def _parse_follow(name: str, index: int, raw) -> Optional[FollowRule]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise SiteConfigError(f"[{name}] listings[{index}].follow はマッピングである必要があります")
    return FollowRule(
        link_text=raw.get("link_text", ""),
        max_pages=int(raw.get("max", 30)),
        delay_ms=int(raw.get("delay_ms", 1500)),
        wait_ms=int(raw.get("wait_ms", 3000)),
        title_prefix=raw.get("title_prefix", ""),
        skip_if_context_contains=raw.get("skip_if_context_contains") or [],
        deadline=DeadlineRule(**(raw.get("deadline") or {})),
        company=CompanyRule(**(raw.get("company") or {})),
    )


def parse_site_config(raw: dict, slug: str = "", variables: Optional[dict] = None) -> SiteConfig:
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
        follow = _parse_follow(name, i, item.get("follow"))
        listings.append(Listing(
            url=_substitute(item["url"], variables or {}),
            wait_ms=int(item.get("wait_ms", 3000)),
            title_prefix=item.get("title_prefix", ""),
            drop_empty_lines=bool(item.get("drop_empty_lines", True)),
            dedupe=bool(item.get("dedupe", True)),
            skip_if_context_contains=item.get("skip_if_context_contains") or [],
            deadline=deadline,
            company=company,
            follow=follow,
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
        login_url=_substitute(login.get("url", ""), variables or {}),
        login_steps=_validate_steps(name, login.get("steps")),
        login_success_url_not_contains=success_check.get("url_not_contains", ""),
        login_success_selector=success_check.get("selector", ""),
        logged_out_marker=success_check.get("logged_out_text", ""),
        listings=listings,
    )


def load_site_configs(sites_dir: str | Path,
                      variables: Optional[dict] = None) -> list[SiteConfig]:
    """sites/*.yaml をすべて読み込む（ファイル名順）

    variables を渡すと、URL 中の {grad_yy} のような変数を置き換える。
    渡さない、または値が足りない場合はそのまま残るので、
    SiteConfig.unresolved_variables() で検出できる。
    """
    sites_dir = Path(sites_dir)
    if not sites_dir.is_dir():
        raise SiteConfigError(f"サイト定義ディレクトリが見つかりません: {sites_dir}")

    configs = []
    for path in sorted(sites_dir.glob("*.y*ml")):
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            continue
        configs.append(parse_site_config(raw, slug=path.stem, variables=variables))
    return configs
