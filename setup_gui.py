#!/usr/bin/env python3
"""設定画面

コマンドやテキストエディタを使わずに、次のことを1つのウィンドウで済ませる。

  - Google の鍵ファイルの取り込みと、共有設定が正しいかの接続テスト
  - カレンダー ID・通知日数などの設定（config.yaml）
  - 使うサイトの選択とログイン情報（sites/*.yaml と .env）
  - 手動ログインが要るサイトのログイン
  - テスト実行と、その場でのログ表示
  - 毎朝の自動実行の登録（タスクスケジューラ）

画面を出さずに動く部分は engine/setup_ops.py と engine/configfile.py にある。
"""
import sys

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 以上が必要です。")

import os  # noqa: E402
import queue  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    sys.exit(
        "この Python には tkinter が入っていません。\n"
        "python.org のインストーラで入れ直し、"
        "「tcl/tk and IDLE」を選んでください。"
    )

import yaml  # noqa: E402

from engine import configfile, runtime, setup_ops  # noqa: E402

CONFIG = os.path.join(BASE_DIR, "config.yaml")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.example.yaml")
KEY_FILE = os.path.join(BASE_DIR, "service_account.json")

PAD = {"padx": 10, "pady": 6}


def load_config() -> dict:
    """config.yaml を読む。無ければ雛形から作る"""
    if not os.path.exists(CONFIG) and os.path.exists(CONFIG_EXAMPLE):
        shutil.copy2(CONFIG_EXAMPLE, CONFIG)
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


class SetupWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("就活カレンダー — 設定")
        self.geometry("760x680")
        self.minsize(700, 560)

        self.config_data = load_config()
        self.site_rows = setup_ops.list_sites(BASE_DIR)
        self.messages = queue.Queue()

        self._build()
        self._refresh_google_status(quick=True)
        self.after(120, self._drain_messages)

    # ------------------------------------------------------------ 画面
    def _build(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        notebook.add(self._build_google_tab(notebook), text="  1. カレンダー  ")
        notebook.add(self._build_sites_tab(notebook), text="  2. 就活サイト  ")
        notebook.add(self._build_run_tab(notebook), text="  3. 実行と自動化  ")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left")
        ttk.Button(bar, text="保存して閉じる", command=self._save_and_close).pack(side="right")
        ttk.Button(bar, text="保存", command=self._save).pack(side="right", padx=6)

    # --- タブ1: カレンダー -------------------------------------------------
    def _build_google_tab(self, parent):
        frame = ttk.Frame(parent)
        cal = self.config_data.get("google_calendar", {})
        settings = self.config_data.get("settings", {})

        ttk.Label(
            frame,
            text="Google カレンダーに直接書き込む設定です。\n"
                 "Google Cloud の設定をしたくない場合は、3番目のタブの\n"
                 "「ICS ファイルを書き出す」を使えば、ここは空のままで構いません。",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", **PAD)

        # 鍵ファイル
        ttk.Label(frame, text="サービスアカウントの鍵").grid(row=1, column=0, sticky="w", **PAD)
        self.key_label = ttk.Label(frame, text="", foreground="#555")
        self.key_label.grid(row=1, column=1, sticky="w", **PAD)
        ttk.Button(frame, text="鍵を選ぶ…", command=self._pick_key).grid(row=1, column=2, sticky="e", **PAD)

        # サービスアカウントのアドレス（共有相手）
        ttk.Label(frame, text="共有先アドレス").grid(row=2, column=0, sticky="w", **PAD)
        self.sa_email = tk.StringVar(value="")
        entry = ttk.Entry(frame, textvariable=self.sa_email, state="readonly")
        entry.grid(row=2, column=1, sticky="ew", **PAD)
        ttk.Button(frame, text="コピー", command=self._copy_sa_email).grid(row=2, column=2, sticky="e", **PAD)

        ttk.Label(
            frame,
            text="↑ このアドレスを Google カレンダーの「設定と共有」→\n"
                 "「特定のユーザーやグループと共有する」に貼り、\n"
                 "「予定の変更権限」を与えてください。",
            justify="left", foreground="#555",
        ).grid(row=3, column=0, columnspan=3, sticky="w", **PAD)

        # カレンダー ID
        ttk.Label(frame, text="カレンダー ID").grid(row=4, column=0, sticky="w", **PAD)
        self.calendar_id = tk.StringVar(value=cal.get("calendar_id", ""))
        ttk.Entry(frame, textvariable=self.calendar_id).grid(row=4, column=1, sticky="ew", **PAD)
        ttk.Button(frame, text="接続テスト", command=self._test_google).grid(row=4, column=2, sticky="e", **PAD)

        # 通知・期間
        opts = ttk.Frame(frame)
        opts.grid(row=5, column=0, columnspan=3, sticky="w", **PAD)

        # 卒業予定年（マイナビのように URL に年度が入るサイトで使う）
        ttk.Label(opts, text="卒業予定年").grid(row=0, column=0, sticky="w")
        self.grad_year = tk.StringVar(value=str(setup_ops.grad_year(BASE_DIR)))
        ttk.Spinbox(opts, from_=2020, to=2040, width=8,
                    textvariable=self.grad_year).grid(row=0, column=1, padx=8)
        ttk.Label(opts, text="（マイナビの URL に使われます。3年生・院1年なら今の年度+2）",
                  foreground="#555").grid(row=0, column=2, columnspan=2, sticky="w")

        ttk.Label(opts, text="通知するタイミング（日前・カンマ区切り）").grid(row=1, column=0, sticky="w")
        self.reminder_days = tk.StringVar(
            value=", ".join(str(d) for d in cal.get("reminder_days", [3, 1])))
        ttk.Entry(opts, textvariable=self.reminder_days, width=12).grid(row=1, column=1, padx=8)
        ttk.Label(opts, text="何日先まで拾うか").grid(row=1, column=2, sticky="w", padx=(20, 0))
        self.days_ahead = tk.StringVar(value=str(settings.get("days_ahead", 90)))
        ttk.Entry(opts, textvariable=self.days_ahead, width=8).grid(row=1, column=3, padx=8)

        # 診断結果
        self.google_status = tk.Text(frame, height=8, wrap="word", relief="solid", borderwidth=1)
        self.google_status.grid(row=6, column=0, columnspan=3, sticky="nsew", **PAD)
        self.google_status.configure(state="disabled")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)
        return frame

    # --- タブ2: サイト -----------------------------------------------------
    def _build_sites_tab(self, parent):
        outer = ttk.Frame(parent)
        ttk.Label(
            outer,
            text="使うサイトにチェックを入れてください。\n"
                 "マイナビ・リクナビは、ボタンを押して開くブラウザで一度ログインします\n"
                 "（2段階認証があるため、ID とパスワードの保存では通れません）。",
            justify="left",
        ).pack(anchor="w", **PAD)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        scroll.pack(side="right", fill="y", pady=6)

        self.site_widgets = {}
        for row in self.site_rows:
            self.site_widgets[row.slug] = self._build_site_box(inner, row)
        return outer

    def _build_site_box(self, parent, row):
        box = ttk.LabelFrame(parent, text=f"  {row.name}  ")
        box.pack(fill="x", expand=True, padx=6, pady=6)

        enabled = tk.BooleanVar(value=row.enabled)
        ttk.Checkbutton(box, text="このサイトを巡回する", variable=enabled).grid(
            row=0, column=0, columnspan=3, sticky="w", **PAD)

        widgets = {"enabled": enabled}

        if row.manual_login:
            state = ttk.Label(box, text=f"ログイン状態: {row.session_state}")
            state.grid(row=1, column=0, sticky="w", **PAD)
            ttk.Button(box, text="ブラウザでログインする",
                       command=lambda r=row: self._login(r)).grid(row=1, column=2, sticky="e", **PAD)
            widgets["state_label"] = state
        elif row.needs_credentials:
            ttk.Label(box, text="メールアドレス").grid(row=1, column=0, sticky="w", **PAD)
            email = tk.StringVar(value=row.env_values.get("email", ""))
            ttk.Entry(box, textvariable=email).grid(row=1, column=1, columnspan=2, sticky="ew", **PAD)

            ttk.Label(box, text="パスワード").grid(row=2, column=0, sticky="w", **PAD)
            password = tk.StringVar(value=row.env_values.get("password", ""))
            field = ttk.Entry(box, textvariable=password, show="•")
            field.grid(row=2, column=1, sticky="ew", **PAD)

            show = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                box, text="表示", variable=show,
                command=lambda f=field, v=show: f.configure(show="" if v.get() else "•"),
            ).grid(row=2, column=2, sticky="w", **PAD)

            widgets.update(email=email, password=password)
        else:
            ttk.Label(box, text="ログイン不要").grid(row=1, column=0, sticky="w", **PAD)

        box.columnconfigure(1, weight=1)
        return widgets

    # --- タブ3: 実行 -------------------------------------------------------
    def _build_run_tab(self, parent):
        frame = ttk.Frame(parent)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", **PAD)
        ttk.Button(buttons, text="テスト実行（書き込まない）",
                   command=lambda: self._run_main(["--dry-run"])).pack(side="left")
        ttk.Button(buttons, text="ICS ファイルを書き出す",
                   command=lambda: self._run_main(["--ics"])).pack(side="left", padx=8)
        ttk.Button(buttons, text="カレンダーに登録",
                   command=self._run_sync).pack(side="left")

        # 自動実行
        auto = ttk.LabelFrame(frame, text="  毎日の自動実行  ")
        auto.pack(fill="x", **PAD)
        self.auto_hour = tk.StringVar(value="8")
        ttk.Label(auto, text="毎朝").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Spinbox(auto, from_=0, to=23, width=4, textvariable=self.auto_hour).grid(row=0, column=1, pady=6)
        ttk.Label(auto, text="時に実行する").grid(row=0, column=2, sticky="w", **PAD)
        ttk.Button(auto, text="登録する", command=self._install_task).grid(row=0, column=3, **PAD)
        ttk.Button(auto, text="解除する", command=self._remove_task).grid(row=0, column=4, **PAD)

        if not setup_ops.scheduler_available():
            ttk.Label(auto, text="（この機能は Windows でのみ使えます）",
                      foreground="#a00").grid(row=1, column=0, columnspan=5, sticky="w", **PAD)

        ttk.Label(frame, text="実行ログ").pack(anchor="w", padx=10)
        self.log = tk.Text(frame, wrap="none", relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        return frame

    # ------------------------------------------------------------ 動作
    def _pick_key(self):
        path = filedialog.askopenfilename(
            title="サービスアカウントの JSON 鍵を選ぶ",
            filetypes=[("JSON ファイル", "*.json"), ("すべて", "*.*")])
        if not path:
            return
        check = setup_ops.read_service_account(path)
        if not check.ok:
            messagebox.showerror("この鍵は使えません", f"{check.title}\n\n{check.detail}")
            return
        if os.path.abspath(path) != os.path.abspath(KEY_FILE):
            shutil.copy2(path, KEY_FILE)
        self._refresh_google_status(quick=True)
        self._set_status("鍵を取り込みました")

    def _copy_sa_email(self):
        value = self.sa_email.get()
        if not value:
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        self._set_status("共有先アドレスをコピーしました")

    def _refresh_google_status(self, quick: bool = False):
        """quick=True ならネットワークを使わない範囲だけ確認する"""
        check = setup_ops.read_service_account(KEY_FILE)
        self.key_label.configure(
            text=os.path.basename(KEY_FILE) if check.ok else "未設定")
        if check.sa_email:
            self.sa_email.set(check.sa_email)
        if quick:
            self._show_google(check)

    def _test_google(self):
        self._show_google(setup_ops.Check(True, "確認しています…", ""))
        self._in_background(
            lambda: setup_ops.check_google(BASE_DIR, self.calendar_id.get()),
            self._show_google)

    def _show_google(self, check):
        if check.sa_email:
            self.sa_email.set(check.sa_email)
        mark = "OK" if check.ok else "確認が必要"
        self.google_status.configure(state="normal")
        self.google_status.delete("1.0", "end")
        self.google_status.insert("end", f"[{mark}] {check.title}\n\n{check.detail}")
        self.google_status.configure(state="disabled")

    def _login(self, row):
        self._save()
        self._append_log(f"=== {row.name}: ブラウザを開きます ===\n")
        self._append_log("ログインし終えたら、開いた黒い画面で Enter を押してください。\n")
        exe = setup_ops.python_exe(BASE_DIR)
        if not exe:
            messagebox.showerror("実行できません", "先に setup.bat を実行してください。")
            return
        # 手動ログインは入力待ちがあるので、コンソールを持った別窓で動かす
        creation = subprocess.CREATE_NEW_CONSOLE if runtime.IS_WINDOWS else 0
        subprocess.Popen([exe, os.path.join(BASE_DIR, "main.py"), "--login", row.slug],
                         cwd=BASE_DIR, creationflags=creation)

    def _run_sync(self):
        if not messagebox.askokcancel(
                "確認", "Google カレンダーに予定を登録します。よろしいですか？"):
            return
        self._run_main([])

    def _run_main(self, args):
        self._save()
        exe = setup_ops.python_exe(BASE_DIR)
        if not exe:
            messagebox.showerror("実行できません", "先に setup.bat を実行してください。")
            return
        self.log.delete("1.0", "end")
        self._append_log(f"$ main.py {' '.join(args)}\n\n")
        self._in_background(lambda: self._stream(exe, args), lambda _: None)

    def _stream(self, exe, args):
        env = dict(os.environ)
        # 子プロセスの出力を必ず UTF-8 で受け取る（Windows の既定は cp932）
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        creation = subprocess.CREATE_NO_WINDOW if runtime.IS_WINDOWS else 0
        proc = subprocess.Popen(
            [exe, os.path.join(BASE_DIR, "main.py")] + args,
            cwd=BASE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=creation)
        for line in proc.stdout:
            self.messages.put(("log", line))
        proc.wait()
        self.messages.put(("log", f"\n--- 終了コード {proc.returncode} ---\n"))
        return None

    def _install_task(self):
        try:
            hour = int(self.auto_hour.get())
        except ValueError:
            messagebox.showerror("時刻が不正です", "0〜23 の数字を入れてください。")
            return
        ok, message = setup_ops.run_schtasks(setup_ops.create_task_args(BASE_DIR, hour))
        self._append_log(f"[自動実行の登録] {message}\n")
        if ok:
            messagebox.showinfo(
                "登録しました",
                f"毎朝 {hour} 時に自動で実行します。\n\n"
                "ノートパソコンを閉じている時間帯なら、タスク スケジューラの\n"
                "プロパティ →「条件」で「タスクを実行するためにスリープを解除する」に\n"
                "チェックを入れてください。")
        else:
            messagebox.showerror("登録できませんでした", message)

    def _remove_task(self):
        ok, message = setup_ops.run_schtasks(setup_ops.delete_task_args())
        self._append_log(f"[自動実行の解除] {message}\n")
        messagebox.showinfo("解除", "解除しました。" if ok else message)

    # ------------------------------------------------------------ 保存
    def _collect(self):
        cal, settings = {}, {}
        if self.calendar_id.get().strip():
            cal["google_calendar.calendar_id"] = self.calendar_id.get().strip()

        days = [int(d) for d in self.reminder_days.get().replace("、", ",").split(",")
                if d.strip().isdigit()]
        if days:
            cal["google_calendar.reminder_days"] = days
        if self.days_ahead.get().strip().isdigit():
            settings["settings.days_ahead"] = int(self.days_ahead.get())
        if self.grad_year.get().strip().isdigit():
            settings["settings.grad_year"] = int(self.grad_year.get())

        for row in self.site_rows:
            w = self.site_widgets[row.slug]
            row.enabled = bool(w["enabled"].get())
            if "email" in w:
                row.env_values["email"] = w["email"].get().strip()
                row.env_values["password"] = w["password"].get()
        return {**cal, **settings}

    def _save(self):
        try:
            updates = self._collect()
            if not os.path.exists(CONFIG) and os.path.exists(CONFIG_EXAMPLE):
                shutil.copy2(CONFIG_EXAMPLE, CONFIG)
            if updates and os.path.exists(CONFIG):
                configfile.set_yaml_values(CONFIG, updates)
            setup_ops.save_sites(BASE_DIR, self.site_rows)
        except Exception as e:
            messagebox.showerror("保存できませんでした", str(e))
            return False
        self._set_status("保存しました")
        return True

    def _save_and_close(self):
        if self._save():
            self.destroy()

    # ------------------------------------------------------------ 小道具
    def _in_background(self, work, done):
        def runner():
            try:
                result = work()
            except Exception as e:  # 画面が固まるより、内容を出して次に進める
                result = setup_ops.Check(False, "エラーが起きました", str(e))
            self.messages.put(("done", (done, result)))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_messages(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                else:
                    callback, result = payload
                    callback(result)
        except queue.Empty:
            pass
        self.after(120, self._drain_messages)

    def _append_log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def _set_status(self, text):
        self.status.configure(text=text)
        self.after(4000, lambda: self.status.configure(text=""))


def main():
    runtime.setup()
    try:
        SetupWindow().mainloop()
    except Exception:
        # pythonw.exe で起動するとコンソールが無く、例外がどこにも出ない。
        # 何が起きたか分かるようにファイルへ残し、画面にも出す。
        import traceback
        detail = traceback.format_exc()
        log_path = os.path.join(BASE_DIR, "setup_gui_error.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(detail)
        except OSError:
            pass
        try:
            messagebox.showerror("設定画面でエラーが起きました",
                                 f"{detail}\n\n詳細は {log_path} に保存しました。")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
