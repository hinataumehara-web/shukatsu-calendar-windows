"""ログインセッション（Cookie 等）の保存と再利用

なぜ必要か
----------
マイナビ（My CareerID）は新しいブラウザからログインすると6桁の確認コードを
メールで要求する。リクナビはログイン導線が JavaScript で組まれていて、
CSS クラス名がビルドごとに変わる（styles_button__XwAS7 のような名前）。
どちらも「YAML にセレクタを書いて毎回自動ログインする」方式では続かない。

そこで、最初の1回だけ人間がブラウザでログインし、その状態
（Cookie と localStorage）をファイルに保存して以後は使い回す。
2回目からはログイン画面を通らないので、確認コードもセレクタ崩れも関係なくなる。

    python main.py --login mynavi     # ブラウザが開く。手でログインする
    python main.py --dry-run          # 以後は保存された状態で巡回する

保存先は .sessions/<slug>.json（.gitignore 済み）。
ログイン済み Cookie が入っているので、パスワードと同じ扱いで管理すること。
"""
import json
import os
import time

SESSION_DIR = ".sessions"

# 何日経ったセッションを「古い」とみなすか（サイト側の Cookie 期限とは別の目安）
DEFAULT_MAX_AGE_DAYS = 25


def session_dir(base_dir: str) -> str:
    return os.path.join(base_dir, SESSION_DIR)


def session_path(base_dir: str, slug: str) -> str:
    return os.path.join(session_dir(base_dir), f"{slug}.json")


def exists(base_dir: str, slug: str) -> bool:
    path = session_path(base_dir, slug)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def age_days(base_dir: str, slug: str):
    """保存からの経過日数。無ければ None"""
    path = session_path(base_dir, slug)
    if not os.path.isfile(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 86400.0


def is_stale(base_dir: str, slug: str, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> bool:
    age = age_days(base_dir, slug)
    return age is None or age > max_age_days


def save(base_dir: str, slug: str, state: dict) -> str:
    """Playwright の storage_state を書き出す"""
    directory = session_dir(base_dir)
    os.makedirs(directory, exist_ok=True)
    # Windows でも他ユーザーから読めないように、可能なら権限を絞る
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    path = session_path(base_dir, slug)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load_path(base_dir: str, slug: str):
    """Playwright の new_context(storage_state=...) に渡すパス。無ければ None"""
    return session_path(base_dir, slug) if exists(base_dir, slug) else None


def describe(base_dir: str, slug: str) -> str:
    """人が読む用の状態説明"""
    if not exists(base_dir, slug):
        return "未保存"
    age = age_days(base_dir, slug)
    return f"保存済み（{age:.1f} 日前）"
