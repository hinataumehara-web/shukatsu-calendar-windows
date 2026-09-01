# shukatsu-calendar for Windows

就活サイトのエントリー締切を自動で収集し、Google カレンダーに登録するツールの
**Windows 版**。[shukatsu-calendar](https://github.com/hinataumehara-web/shukatsu-calendar)
を Windows でそのまま動くように整えたもの（mac / Linux でも同じように動く）。

締切は各サイトのマイページに散らばっていて、見落とすと取り返しがつかない。
このツールは毎日決まった時刻に各サイトを巡回し、見つけた締切を
「3日前・前日に通知が来る終日予定」としてカレンダーに入れる。同じ予定は二度登録しない。

```
> run.bat --dry-run
2026-04-17 12:00:01 [INFO] === type就活 開始 ===
2026-04-17 12:00:17 [INFO] type就活: ログイン完了
2026-04-17 12:00:22 [INFO] type就活: 22 件抽出
2026-04-17 12:00:22 [INFO] 合計 22 件の締切を検出
  2026-04-18  [type就活] 株式会社◯◯ / 【インターン締切】3days 仕事体験
  2026-04-21  [type就活] △△株式会社 / 【インターン締切】キャリア形成プログラム
2026-04-17 12:00:22 [INFO] dry-run のためカレンダーには書き込みませんでした
```

## Windows 版で変えたところ

元のリポジトリは mac 前提（`python3`、`source .venv/bin/activate`、launchd）で書かれていて、
Windows では動かないか、動いても途中で落ちる箇所があった。主な変更は次のとおり。

| 変わった点 | 直っていないと何が起きるか |
|---|---|
| `setup.bat` / `run.bat` / `dry_run.bat` を同梱 | コマンドを打たずにダブルクリックで始められる |
| ログファイルを UTF-8 で開くよう明示 | Windows の既定は cp932。企業名に絵文字が混ざると `UnicodeEncodeError` で落ちる |
| 標準出力を「変換できない文字は `?` に落とす」設定に | 同上。コンソール表示だけのために処理全体が止まるのを防ぐ |
| `pythonw.exe`（コンソール無し）での実行に対応 | `sys.stdout` が `None` になり、ログ初期化の時点で落ちる |
| asyncio を ProactorEventLoop に明示 + 終了時ノイズを抑制 | Playwright はサブプロセスを使うので必須。終了時に無害な `Event loop is closed` が出て失敗に見える |
| スクリーンショット等の保存先をリポジトリ直下に固定 | タスクスケジューラでは作業フォルダが `C:\Windows\System32` になることがあり、相対パスで書き込めない |
| `.env` を BOM 付き UTF-8 でも読めるように | メモ帳や PowerShell の `>` は BOM を付ける。1行目の変数名だけ読めなくなる |
| Python 3.10 未満なら分かりやすく停止 | そうしないと `TypeError: unsupported operand type(s) for |` という無関係に見えるエラーで落ちる |
| `--list-sites` / `--dry-run` を Google 系ライブラリ無しでも動くように | 認証を設定する前に、まず動くかどうかを確かめられる |
| `.gitattributes` で `.bat` を CRLF 固定 | clone の設定次第で LF になり、cmd.exe が誤動作する |
| CI を Windows / macOS / Ubuntu × Python 3.10・3.12 に | Windows で壊れたことに気づけるようにする |

## 動作環境

- Windows 10 / 11（64bit）
- Python 3.10 以上（3.12 推奨）
- ディスク空き容量 500MB 程度（Playwright が Chromium をダウンロードする）

## セットアップ

### 0. 置き場所を決める

`C:\shukatsu-calendar` のような**浅くて日本語やスペースを含まないパス**に置くこと。
OneDrive の同期対象フォルダ（`ドキュメント` など）は、同期の途中で
`.venv` の中身が壊れることがあるので避ける。

### 1. Python を入れる

[python.org のダウンロードページ](https://www.python.org/downloads/windows/)から
Python 3.12 のインストーラを取得する。インストーラの最初の画面で
**「Add python.exe to PATH」に必ずチェックを入れる**。

> Microsoft Store 版の Python でも動くが、インストール先の権限まわりで
> `.venv` の作成に失敗することがある。うまくいかない場合は python.org 版を使う。

確認：

```bat
py -3 --version
```

`Python 3.12.x` のように出れば OK。

### 2. コードを取得する

Git を使うなら：

```bat
git clone https://github.com/hinataumehara-web/shukatsu-calendar-windows.git C:\shukatsu-calendar
cd C:\shukatsu-calendar
```

Git を入れていないなら、GitHub の緑の **Code** ボタン →
**Download ZIP** で落として展開しても構わない。

### 3. setup.bat を実行する

`setup.bat` をダブルクリックする。次の4つを自動でやる。

1. 仮想環境 `.venv` を作る
2. `requirements.txt` の依存をインストールする
3. Playwright 用の Chromium をダウンロードする
4. `.env` と `config.yaml` を雛形からコピーする

完了まで数分かかる。`Setup finished.` と出れば成功。

<details>
<summary>コマンドで手動でやる場合</summary>

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env
copy config.example.yaml config.yaml
```

`.venv\Scripts\activate` を実行する必要はない。
`.venv\Scripts\python.exe` を直接呼べば、その仮想環境の Python が使われる。
（PowerShell で `Activate.ps1` を実行しようとすると実行ポリシーで拒否されることがあるが、
このツールでは有効化そのものが不要なので気にしなくてよい）

</details>

### 4. サイトのログイン情報を書く

`.env` をメモ帳などで開き、各サイトのメールアドレスとパスワードを入れる。

```
BIZREACH_CAMPUS_EMAIL=you@example.com
BIZREACH_CAMPUS_PASSWORD=********
```

変数名は `sites\*.yaml` の `credentials.*_env` と対応している。
使わないサイトは `sites\<slug>.yaml` の `enabled: false` にしておけばよい。

> **注意**: エクスプローラーで新規作成すると `.env.txt` になりがち。
> 「表示」→「ファイル名拡張子」にチェックを入れて、名前が `.env` であることを確認する。

### 5. Google カレンダーの認証（サービスアカウント方式・推奨）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作り、
   **Google Calendar API** を有効化する
2. 「IAM と管理」→「サービス アカウント」→ サービスアカウントを作成（ロールの付与は不要）
3. 作成したアカウント →「キー」→「鍵を追加」→ **JSON** をダウンロードし、
   `service_account.json` という名前でこのフォルダの直下に置く
4. サービスアカウントのメールアドレス（`...@....iam.gserviceaccount.com`）をコピーし、
   Google カレンダーの「設定と共有」→「特定のユーザーやグループと共有する」で
   **「予定の変更権限」** を与える
5. `config.yaml` の `calendar_id` を自分のカレンダー ID にする

> **なぜサービスアカウントなのか**: OAuth のユーザー認証は、OAuth 同意画面が「テスト」
> ステータスのままだとリフレッシュトークンが発行から7日で失効し、`invalid_grant` で
> 静かに止まる。本番公開するにはプライバシーポリシー URL などの用意が必要で、
> 個人ツールには重い。サービスアカウントなら同意画面の設定自体が不要で、失効もしない。

> **通知について**: Google カレンダーの通知は「予定を作った人」ではなく「見る人」の
> 設定に紐づく。サービスアカウントが共有カレンダーに入れた予定には、`reminder_days` ではなく
> 閲覧者側のデフォルト通知が適用されることがある。確実に通知したい場合は専用カレンダーを作り、
> そのカレンダーの通知設定を「3日前」「前日」にしておくとよい。

### 6. 動作確認

```bat
run.bat --list-sites     :: 定義されているサイトの一覧
run.bat --dry-run        :: 書き込まずに検出結果だけ見る
run.bat                  :: 実際にカレンダーへ登録
```

`dry_run.bat` はダブルクリックで `--dry-run` を実行するためのショートカット。

`--list-sites` と `--dry-run` は Google の認証情報が無くても動くので、
まずここまで通ることを確認してから認証を設定してもよい。

## 定期実行（タスクスケジューラ）

毎朝8時に自動で実行する設定。

### GUI で設定する

1. スタートメニューで「タスク スケジューラ」を開く
2. 右側の「**基本タスクの作成**」
3. 名前: `shukatsu-calendar` → 次へ
4. トリガー: 「毎日」→ 開始時刻 `8:00:00` → 次へ
5. 操作: 「プログラムの開始」→ 次へ
6. 次の3つを入れる（パスは自分の置き場所に合わせる）

   | 欄 | 入れる値 |
   |---|---|
   | プログラム/スクリプト | `C:\shukatsu-calendar\.venv\Scripts\pythonw.exe` |
   | 引数の追加 | `main.py` |
   | 開始（オプション） | `C:\shukatsu-calendar` |

7. 完了 → 作成したタスクを右クリック →「プロパティ」→「条件」タブで
   **「タスクを実行するためにスリープを解除する」にチェック**
   （ノート PC を閉じている時間帯に設定するなら必須）

`python.exe` ではなく **`pythonw.exe`** を指定するのがポイント。
黒いコンソールウィンドウが毎朝ポップアップしなくなる。
実行の記録は `shukatsu.log` に残る。

### コマンドで設定する

管理者権限のコマンドプロンプトで：

```bat
schtasks /create /tn "shukatsu-calendar" /sc daily /st 08:00 ^
  /tr "\"C:\shukatsu-calendar\.venv\Scripts\pythonw.exe\" \"C:\shukatsu-calendar\main.py\""
```

設定ファイル・ログ・サイト定義はすべて `main.py` の場所を基準に読み書きするので、
作業フォルダを指定しなくても動く。

確認・削除：

```bat
schtasks /query /tn "shukatsu-calendar"
schtasks /run   /tn "shukatsu-calendar"     :: 今すぐ1回実行してみる
schtasks /delete /tn "shukatsu-calendar" /f
```

**失敗に気づける仕組みを用意しておくこと。** 認証切れやセレクタ変更でこの手のツールは
静かに止まる。`shukatsu.log` の末尾の日付が古くなっていないか、たまに確認するとよい。

## うまくいかないとき

| 症状 | 原因と対処 |
|---|---|
| `py` や `python` が見つからない | PATH に入っていない。Python を入れ直して「Add python.exe to PATH」にチェック。Microsoft Store のプレースホルダが反応している場合は「設定 → アプリ → アプリ実行エイリアス」で `python.exe` をオフにする |
| `Activate.ps1 を読み込めません` | PowerShell の実行ポリシー。**このツールでは venv の有効化は不要**なので `.venv\Scripts\python.exe` を直接呼べばよい。どうしても有効化したいなら `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `pip install` が失敗する | 社内プロキシの可能性。`set HTTPS_PROXY=http://proxy:8080` を設定してから再実行 |
| `playwright install chromium` が途中で止まる | ウイルス対策ソフトかプロキシがダウンロードを止めている。一時的に除外設定を入れる |
| コンソールの日本語が `?` や文字化けになる | 表示だけの問題。`shukatsu.log` には正しい文字で記録されている。表示も直したければコンソールで `chcp 65001` を実行してから `run.bat` |
| `TypeError: unsupported operand type(s) for \|` | Python が 3.9 以下。3.10 以上を入れて `.venv` を作り直す（`.venv` フォルダを削除して `setup.bat` を再実行） |
| `.env` を書いたのに「環境変数が設定されていません」と出る | ファイル名が `.env.txt` になっている、または1行目だけ BOM で読めていない。拡張子を表示して確認する |
| タスクスケジューラでは動かないが手動なら動く | 「開始（オプション）」にフォルダを指定しているか、パスが絶対パスか確認。まず `schtasks /run` で手動起動して `shukatsu.log` を見る |
| `Event loop is closed` が出る | このリポジトリでは抑制済み。それでも出る場合は処理自体は完了していることが多いので、`shukatsu.log` の結果行を確認する |
| 締切が0件しか取れない | サイト側の HTML が変わった可能性が高い。下の「新しいサイトに対応する」の調査ツールで確認する |

## 新しいサイトに対応する

`sites\example_site.yaml` がスキーマ全項目つきのテンプレート。これをコピーして書き換える。

```bat
copy sites\example_site.yaml sites\mynavi.yaml
```

締切行のパターンを調べるには調査ツールを使う。ログインして一覧ページを開き、
表示テキストを行番号つきで書き出す。

```bat
.venv\Scripts\python.exe tools\inspect_site.py mynavi --grep 締切
.venv\Scripts\python.exe tools\inspect_site.py mynavi --headed --no-login
```

出力を見て、締切を示す行の形（`締切` だけの行なのか `2026年5月21日まで` のような行なのか）と、
会社名がその何行前に出るかを確認し、YAML の `deadline` と `company` を調整する。
調整できたら `run.bat --site mynavi --dry-run` で確認する。

### 同梱のサイト定義

| slug | サイト | 状態 |
|---|---|---|
| `bizreach_campus` | ビズリーチ・キャンパス | 2026-04 動作確認 |
| `type_shukatsu` | type就活 | 2026-04 動作確認 |
| `gaishishukatsu` | 外資就活ドットコム | 要調整（0件しか取得できていない） |

サイト側の改修でセレクタは壊れる。動かなくなったら上の手順で YAML を直してほしい。

## 仕組み

```
sites/*.yaml ──▶ GenericScraper ──▶ DeadlineEntry ──▶ CalendarClient ──▶ Google カレンダー
  サイト定義      Playwright で        締切1件を表す      重複を除いて登録
                  ログイン・巡回        データクラス
```

一覧ページの DOM 構造はサイトごとに大きく異なるが、**画面に表示されるテキストの並び**は
どのサイトでも「タイトル → 会社名 → 締切日」のように似た順序になる。
そこでこのツールは `body` のテキストを行に分解し、

1. 「締切行」を見つける（完全一致 / 正規表現 / キーワードのいずれかで判定）
2. その行または周辺から日付を読む
3. 数行前まで遡り、ノイズ行を除いた最後の候補を会社名、その1つ前をタイトルとする

という手順を取る。この3つのパラメータが `sites/*.yaml` に書かれている。

サイト追加に Python を書かなくてよいのはこのため。サイトの HTML が変わったときも
YAML を直すだけで済む。

## ディレクトリ構成

```
├── setup.bat                初回セットアップ（Windows）
├── run.bat                  実行（Windows）
├── dry_run.bat              --dry-run のショートカット
├── main.py                  エントリポイント（--dry-run / --site / --list-sites）
├── engine/
│   ├── runtime.py           OS 差異の吸収（Windows 対応の中身はここ）
│   ├── site_config.py       サイト定義 YAML の読み込みとバリデーション
│   ├── scraper.py           YAML どおりに動く汎用スクレイパー
│   ├── calendar_client.py   Google カレンダーへの登録・重複チェック
│   ├── dateparse.py         日本語の日付表記のパーサ
│   └── models.py            DeadlineEntry
├── sites/                   サイト定義（example_site.yaml がテンプレート）
├── tools/inspect_site.py    ページテキストを調べる調査ツール
└── tests/                   pytest
```

## mac / Linux で使う

Windows 専用にしたわけではないので、そのまま動く。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env
cp config.example.yaml config.yaml
.venv/bin/python main.py --dry-run
```

定期実行は cron（`0 8 * * * cd /path/to/shukatsu-calendar && .venv/bin/python main.py`）か
launchd を使う。

## テスト

```bat
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest -q
```

同梱サイト定義が壊れていないこと、日付パーサ、認証情報が YAML に混入していないこと、
そして Windows 対応で入れた仕掛け（`.bat` が CRLF であること、`sys.stdout` が
`None` でも落ちないこと、UTF-8 でログが書けること）を検証している。

## セキュリティ

以下は `.gitignore` 済み。**間違ってもコミットしないこと。**

| ファイル | 中身 |
|---|---|
| `.env` | 各就活サイトのログイン情報 |
| `service_account.json` | Google の秘密鍵 |
| `credentials.json` / `token.json` | OAuth のクライアントシークレットとトークン |
| `config.yaml` | カレンダー ID（個人のメールアドレス） |
| `*.log` / `debug_*.png` / `inspect_*.txt` | 応募先の企業名など個人の就活状況 |

一度コミットしてしまった秘密情報は、履歴から消してもリモートに残る可能性がある。
その場合は速やかに該当パスワード・鍵を無効化して作り直すこと。

## 免責

- 本ツールは各サイトの公式なものではなく、いかなる形でも提携していない
- 自動アクセスやスクレイピングを禁じている場合がある。**利用前に必ず各サイトの利用規約を
  確認し、自己責任で使用すること**
- 抽出は画面テキストのヒューリスティックに基づくため、**取りこぼしや誤検出が起こりうる**。
  重要な締切は必ず公式サイトで確認すること
- 短時間に繰り返し実行せず、1日1回程度の実行にとどめること

## ライセンス

MIT License — [LICENSE](LICENSE) を参照。
