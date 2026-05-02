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
デスクトップランチャーも同時に使う場合は、Python 環境へ `launcher/requirements.txt` も入れます。

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

### 2. `python run.py`

用途:

- 配布先での通常起動
- Node.js / npm がない端末での起動

前提:

- Python
- `frontend/dist/` がリポジトリに含まれていること
- デスクトップランチャーを使う場合は `launcher/requirements.txt` の依存も入っていること

動作:

- `frontend/dist/` が存在すれば FastAPI からそのまま配信する
- 既定では `127.0.0.1:8079` で起動する
- 必要なら `SEARCH_APP_HOST` と `SEARCH_APP_PORT` で上書きできる
- `backend/run.py` は既定で `SEARCH_APP_LAUNCHER_AUTOSTART=1` を設定し、ランチャーを子プロセスとして起動する

## 配布先での手順

### 初回のみ

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r ..\launcher\requirements.txt
```

### 毎回の起動

```powershell
cd backend
.venv\Scripts\python.exe run.py
```

既定のアクセス先:

- `http://127.0.0.1:8079/`

外部アプリから特定フォルダと検索語を渡して開く場合:

- `http://127.0.0.1:8079/?q=見積&full_path=%2FUsers%2Fmine%2FDocuments&index_depth=2`
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

- Host: `127.0.0.1`
- Port: `8079`
- DB 保存先: 起動ディレクトリに依存せず `backend/data/search.db`

## 保存されるファイル

既定では `backend/data/` 配下に次のファイルを保存する。

- `search.db`
- `exclude_keywords.txt`
- `hidden_indexed_targets.txt`
- `synonym_groups.txt`
- `obsidian_sidebar_explorer_data_path.txt`
- `search_target_folders.txt`
- `index_selected_extensions.txt`
- `custom_content_extensions.txt`
- `custom_filename_extensions.txt`
- `launcher.log` は `backend/` 直下に保存する

保存先ディレクトリは `SEARCH_APP_DATA_DIR` で、各ファイル名は `SEARCH_APP_*_NAME` 系の環境変数で上書きできる。

## Git 管理方針

配布先でフロントエンドをビルドしないため、`frontend/dist/` は Git 管理対象にします。

引き続き Git 管理しないもの:

- `backend/.venv/`
- `frontend/node_modules/`
- `backend/data/`
- `data/`
- `.run/`
- `*.log`
