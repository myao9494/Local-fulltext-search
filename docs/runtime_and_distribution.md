<!--
配布先での起動方法と、開発環境との差分をまとめる。
会社PCなどで Node.js を入れられない前提でも迷わず起動できるようにする。
-->

# 配布・起動手順

## 目的

このドキュメントは、以下 2 つの起動方法の違いを整理するためのものです。

- 開発用に `start_dev.sh` で一括起動する方法
- 配布先で `backend/run.py` を直接起動する方法

## 結論

会社PCなどでフロントエンドのビルド環境がない場合は、`frontend/dist/` をリポジトリに含めた状態で配布し、`backend/run.py` を直接起動します。

この運用で必要なのは基本的に Python のみです。  
Node.js / npm は、フロントエンドを再ビルドするときだけ必要です。
`backend/requirements.txt` にはデスクトップランチャーの依存関係も含めています。

`launcher/requirements.txt` は、ランチャーだけを単体で動かす環境を最小構成で用意したい場合に使います。

## 起動方法ごとの違い

### 1. `start_dev.sh`

用途:

- 開発環境での一括起動
- フロントエンドを再ビルドしてからバックエンドを起動したいとき

前提:

- Python
- Node.js
- npm

動作:

- `backend/.venv` がなければ作成する
- Python 依存をインストールする
- ランチャー自動起動に必要な Python 依存も `backend/.venv` にインストールする
- `frontend/node_modules` がなければ `npm install` する
- `frontend/dist/` を再ビルドする
- バックエンドを `0.0.0.0:8079` で起動する
- Open/UIハブを `127.0.0.1:8001` で子プロセス起動する

### 2. `python run.py`

用途:

- 配布先での通常起動
- Node.js / npm がない端末での起動

前提:

- Python
- `frontend/dist/` がリポジトリに含まれていること
- デスクトップランチャーを使う場合は `backend/requirements.txt` の依存が入っていること
- Windows の完全オフライン環境でデスクトップランチャーを使う場合は `launcher/vendor/flet-view/` に Flet View を同梱していること

動作:

- `frontend/dist/` が存在すれば FastAPI からそのまま配信する
- 既定では `127.0.0.1:8079` で起動する
- 8001のOpen/UIハブを別プロセスで自動起動し、Web UIとprimary openの入口にする
- 必要なら `SEARCH_APP_HOST` と `SEARCH_APP_PORT` で上書きできる
- `backend/run.py` は既定で `SEARCH_APP_LAUNCHER_AUTOSTART=1` を設定し、ランチャーを子プロセスとして起動する。Windowsでは発行済みWPF通常版、WPF single-file版、Python/Flet版の順に選ぶ
- WPF版EXEを標準の `launcher/windows/publish/` 以外へ置く場合は、`SEARCH_APP_WPF_LAUNCHER_PATH` に絶対パスを指定する

## 配布先での手順

### 初回のみ

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 毎回の起動

```powershell
cd backend
.venv\Scripts\python.exe run.py
```

既定のアクセス先:

- Web/Open: `http://127.0.0.1:8001/`
- Search/API: `http://127.0.0.1:8079/`

ランチャーは`LAUNCHER_API_BASE_URL=http://127.0.0.1:8079`で検索し、`LAUNCHER_WEB_BASE_URL=http://127.0.0.1:8001`で結果を開く。DNS無し環境と別端末の固定IP例、Open契約、障害切り分けは[`open_hub.md`](open_hub.md)を参照する。

## Windows ランチャーの完全オフライン起動

発行済みWPF版がある場合、Flet Viewとランチャー用Python依存は不要である。`start_windows.bat` はバックエンドへランチャー起動を委ねるため、Web画面/APIからWPFプロセスの状態確認・停止・再起動ができる。WPF版がない場合だけ、以下のFlet View準備が必要になる。

Windows の Flet ランチャーは、画面表示用に Flet View という実行ファイル一式を必要とします。Flet は通常、このファイルを初回起動時にネットワークから取得します。完全オフライン環境では取得できないため、配布前に次のどちらかをリポジトリへ入れてください。

- 展開済みディレクトリ: `launcher/vendor/flet-view/windows/flet.exe`
- zip アーカイブ: `launcher/vendor/flet-view/flet-view-windows.zip`

このリポジトリでは Flet を `0.84.0` に固定しています。Windows 用アーカイブは Flet の GitHub Releases から `v0.84.0` の `flet-windows.zip` を取得し、`flet-view-windows.zip` にリネームして `launcher/vendor/flet-view/` へ置きます。

`start_windows.bat` から起動する場合は `LAUNCHER_REQUIRE_OFFLINE_FLET_VIEW=1` が設定されます。Flet View が未配置なら、外部ダウンロードへ進む前に配置先を示して停止します。zip アーカイブを置いた場合は、初回起動時に `launcher/.offline_cache/flet-view/windows/` へ自動展開して `FLET_VIEW_PATH` を設定します。

オンライン準備端末で行うこと:

```powershell
cd backend
python -m pip install -r requirements.txt
python run.py
```

ランチャーが一度起動したら、Flet が取得した Flet View のアーカイブまたは展開済みフォルダを `launcher/vendor/flet-view/` に置いてから、会社PCへリポジトリごと配布します。配置ルールの詳細は `launcher/vendor/flet-view/README.md` を参照してください。

外部アプリから特定フォルダと検索語を渡して開く場合:

- `http://127.0.0.1:8001/?q=見積&full_path=%2FUsers%2Fmine%2FDocuments&index_depth=2`
- `q` と `full_path` の両方があると初回表示時に自動検索する
- `search_all=1` を付けると、`full_path` が空でも初回に全 DB 検索を実行できる
- `index_depth` を省略した場合は `1`
- `full_path` は絶対パス、または Windows の UNC パスを使う

### 別端末からアクセスさせたい場合

```powershell
cd backend
$env:SEARCH_APP_HOST="0.0.0.0"
$env:SEARCH_APP_PORT="8079"
.venv\Scripts\python.exe run.py
```

アクセス先:

- `http://<このPCのIPアドレス>:8079/`

## ポートと bind の既定値

`start_dev.sh` の既定値:

- Host: `0.0.0.0`
- Port: `8079`

`backend/run.py` の既定値:

- Search/API: `127.0.0.1:8079`
- Open/UIハブ: `127.0.0.1:8001`
- DB 保存先: 起動ディレクトリに依存せず `backend/data/search.db`

## 保存されるファイル

既定では `backend/data/` 配下に次のファイルを保存する。

- `search.db`
- `exclude_keywords.txt`
- `web_exclude_keywords.txt`
- `hidden_indexed_targets.txt`
- `synonym_groups.txt`
- `obsidian_sidebar_explorer_data_path.txt`
- `index_selected_extensions.txt`
- `custom_content_extensions.txt`
- `custom_filename_extensions.txt`
- `launcher.log` は `backend/` 直下に保存する

保存先ディレクトリは `SEARCH_APP_DATA_DIR` で、各ファイル名は `SEARCH_APP_*_NAME` 系の環境変数で上書きできる。
検索対象フォルダはテキストファイルではなく SQLite の `targets` テーブルに保存する。

## Git 管理方針

配布先でフロントエンドをビルドしないため、`frontend/dist/` は Git 管理対象にします。

引き続き Git 管理しないもの:

- `backend/.venv/`
- `frontend/node_modules/`
- `backend/data/`
- `data/`
- `launcher/.offline_cache/`
- `.run/`
- `*.log`
