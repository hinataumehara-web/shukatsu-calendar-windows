"""実行環境の差異（主に Windows）を吸収する層

Windows で素直に動かすために必要な小細工をここに集める。
mac / Linux では何もしないか、従来どおりの挙動になる。

ここで面倒を見ているもの:

1. Python のバージョン確認
   本体は `str | None` 記法を使うので 3.10 以上が要る。
   3.9 以下だと意味の分からない TypeError で落ちるため、先に止める。

2. 標準出力の文字化け・クラッシュ
   日本語 Windows のコンソールは既定が cp932。企業名に絵文字や
   cp932 に無い文字が混ざると print / logging が UnicodeEncodeError で
   落ちる。エンコーディング自体は変えず（変えるとコンソール側と
   食い違って化ける）、変換できない文字を "?" に落とす設定にする。

3. pythonw.exe で sys.stdout が None になる問題
   タスクスケジューラからコンソール無しで動かすときに使うが、
   このとき sys.stdout / sys.stderr は None。素朴に
   StreamHandler(sys.stdout) を作ると起動時に落ちる。

4. asyncio のイベントループ
   Playwright はサブプロセスを起動するので Windows では
   ProactorEventLoop が必須。3.8 以降は既定だが、明示しておく。
   さらに終了時に "Event loop is closed" の無害な例外が出るのを黙らせる。
"""
import asyncio
import sys

MIN_PYTHON = (3, 10)

IS_WINDOWS = sys.platform.startswith("win")

_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def check_python_version():
    """古い Python なら分かりやすく止める"""
    if sys.version_info < MIN_PYTHON:
        need = ".".join(str(n) for n in MIN_PYTHON)
        have = ".".join(str(n) for n in sys.version_info[:3])
        sys.exit(
            "Python {0} 以上が必要です（今使われているのは {1}）。\n"
            "python.org から新しい Python を入れ、venv を作り直してください:\n"
            "    py -3.12 -m venv .venv\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
            "使われている実行ファイル: {2}".format(need, have, sys.executable)
        )


def default_user_agent():
    """OS に合った User-Agent（設定で上書きされなければこれを使う）"""
    return _WINDOWS_UA if IS_WINDOWS else _MAC_UA


def configure_stdio():
    """標準出力・標準エラーを「落ちない」設定にする

    pythonw.exe では None なので、その場合は何もしない。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # encoding は変えない。コンソールの実際のコードページと
            # 食い違うと、落ちない代わりに全部が文字化けする。
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def has_console() -> bool:
    """コンソール出力が使えるか（pythonw.exe では False）"""
    return sys.stdout is not None


def _silence_proactor_shutdown_noise():
    """Windows の終了時に出る無害な例外を黙らせる

    ProactorEventLoop のパイプ後始末が GC のタイミングで走ると
    "RuntimeError: Event loop is closed" を標準エラーに吐く。
    処理そのものは成功しているのに失敗したように見えるので抑える。
    """
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
    except ImportError:
        return

    original_del = getattr(_ProactorBasePipeTransport, "__del__", None)
    if original_del is None or getattr(original_del, "_shukatsu_patched", False):
        return

    def quiet_del(self, _original=original_del):
        try:
            _original(self)
        except (RuntimeError, ConnectionResetError, OSError):
            pass

    quiet_del._shukatsu_patched = True
    _ProactorBasePipeTransport.__del__ = quiet_del


def configure_event_loop():
    """Playwright が動くイベントループを用意する（Windows のみ調整）"""
    if not IS_WINDOWS:
        return
    policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy is not None and not isinstance(asyncio.get_event_loop_policy(), policy):
        asyncio.set_event_loop_policy(policy())
    _silence_proactor_shutdown_noise()


def setup():
    """起動直後に一度だけ呼ぶ"""
    check_python_version()
    configure_stdio()
    configure_event_loop()


def run(coro):
    """setup() 済みの前提で非同期処理を実行する"""
    return asyncio.run(coro)
