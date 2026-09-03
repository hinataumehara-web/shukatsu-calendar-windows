"""設定ファイルを「コメントを壊さずに」書き換える

なぜ専用の層があるのか
----------------------
GUI から設定を保存するとき、YAML を読み込んで丸ごと書き戻すと
（PyYAML の dump）、ファイル中の説明コメントが全部消える。
このリポジトリの config.yaml と sites/*.yaml は、コメントそのものが
使い方の説明を兼ねているので、それでは困る。

そこで、値のある行だけを狙って差し替える。行単位の編集なので、
コメント・空行・並び順・インデントはそのまま残る。
"""
import os
import re

# key: value 形式の行（インデントつき）
_KEY_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w.-]*)\s*:(?P<rest>.*)$")

# 値のうしろに続く行末コメント（値の中の # と区別するため、前に空白を要求する）
_TRAILING_COMMENT = re.compile(r"(?P<value>.*?)(?P<comment>\s+#.*)?$")


# --------------------------------------------------------------------- .env
def strip_quotes(value: str) -> str:
    """前後が同じ引用符で囲まれているときだけ外す

    素朴に .strip('"') とすると、末尾が " のパスワードが壊れる。
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_text(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = strip_quotes(value)
    return values


def load_env(path: str) -> dict:
    """.env を読む。BOM 付き（メモ帳・PowerShell の既定）でも読める"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return parse_env_text(f.read())


def _quote_env_value(value: str) -> str:
    """空白・# ・前後の空白を含む値は引用符で囲む

    読み戻す側（strip_quotes）は「前後が同じ引用符ならそれを外す」だけで
    エスケープを解かないので、ここでもエスケープはしない。
    値に含まれない方の引用符を選ぶ。
    """
    if value == "" or (value == value.strip() and " " not in value and "#" not in value):
        return value
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    # 両方の引用符を含む値は囲めない。前後の空白は失われる
    return value


def apply_env(path: str, updates: dict) -> None:
    """既存の .env のコメントと並びを保ったまま、指定のキーだけ書き換える

    ファイルに無いキーは末尾に足す。値が None のキーは触らない。
    """
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return

    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                out.append(f"{key}={_quote_env_value(remaining.pop(key))}")
                continue
        out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        for key, value in remaining.items():
            out.append(f"{key}={_quote_env_value(value)}")

    _write_lines(path, out)


# --------------------------------------------------------------------- YAML
def format_scalar(value) -> str:
    """Python の値を YAML の値の書き方にする"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_scalar(v) for v in value) + "]"
    # 文字列は常に囲む。yes / null / 12:30 のように、囲まないと
    # 別の型に解釈されてしまう値があるため
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"' 


def set_yaml_values(path: str, updates: dict) -> None:
    """YAML の指定キーの値だけ差し替える

    updates のキーは "calendar_id" のような単独キーか、
    "google_calendar.calendar_id" のような「親.子」の形。
    値が None のキーは触らない。
    """
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return

    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    remaining = dict(updates)
    section = None          # 直近の、インデント0のキー（= 親セクション名）
    out = []

    for line in lines:
        m = _KEY_LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            out.append(line)
            continue

        indent, key, rest = m.group("indent"), m.group("key"), m.group("rest")
        if indent == "":
            section = key

        for target in (f"{section}.{key}" if section and indent else None, key):
            if target and target in remaining:
                cm = _TRAILING_COMMENT.match(rest.strip())
                comment = (cm.group("comment") or "") if cm else ""
                new_value = format_scalar(remaining.pop(target))
                out.append(f"{indent}{key}: {new_value}{comment}")
                break
        else:
            out.append(line)

    # 見つからなかったキーは、親セクションの直後に足す
    for target, value in list(remaining.items()):
        parent, _, child = target.rpartition(".")
        out = _insert_under_section(out, parent, child, value)

    _write_lines(path, out)


def _insert_under_section(lines: list, parent: str, key: str, value) -> list:
    entry_indent = "  " if parent else ""
    entry = f"{entry_indent}{key}: {format_scalar(value)}"
    if not parent:
        return lines + [entry]

    out = list(lines)
    for i, line in enumerate(out):
        if _KEY_LINE.match(line) and line.startswith(parent + ":"):
            out.insert(i + 1, entry)
            return out
    return out + [f"{parent}:", entry]


def set_site_enabled(path: str, enabled: bool) -> None:
    """サイト定義の enabled: だけを切り替える"""
    set_yaml_values(path, {"enabled": bool(enabled)})


def read_site_enabled(path: str) -> bool:
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            m = _KEY_LINE.match(line)
            if m and m.group("indent") == "" and m.group("key") == "enabled":
                return m.group("rest").strip().split("#")[0].strip().lower() == "true"
    return True


# --------------------------------------------------------------------- 共通
def _write_lines(path: str, lines: list) -> None:
    """一時ファイルに書いてから置き換える（書き込み中の事故で設定を失わない）"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.replace(tmp, path)
