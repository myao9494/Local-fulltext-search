# local-fulltext-search

ローカルPCおよび必要に応じて Tailscale VPN 経由で私的利用する、全文検索専用の Web アプリです。

## 目的

- **ファイル内容の全文検索**を中心にする
- 画像など本文抽出しないファイルは、補助的にファイル名検索で拾えるようにする
- Google のようなシンプルな検索UIで使えるようにする
- 主にローカル利用を前提としつつ、必要に応じて Tailscale 経由でアクセスできるようにする

## 前提

- インターネット公開はしない
- 一般公開向けの認証・認可は対象外
- CORS / CSRF など公開サービス前提の設定は不要
- 開発は macOS で行う
- Windows でも動作確認・デバッグする
- パス差異に注意し、内部では正規化して扱う

## 想定技術

- Backend: Python + FastAPI
- Frontend: React + Vite
- 配布形態: Vite でビルドした PWA フロントエンドを FastAPI から同一オリジン配信
- Full-text search: SQLite FTS5

## 対応ファイル

### 本文抽出あり
- `.md`
- `.json`
- `.txt`
- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.msg`

### ファイル名のみ検索対象
- `.png`
- `.jpg`
- `.jpeg`
- `.gif`
- `.webp`
- `.heic`
- `.svg`
- `.bmp`
- `.tif`
- `.tiff`

### 将来対応
- `.excalidraw`
- `.drawio`
- `.drawio.svg`

## 仕様書

- 全体仕様: `spec/product_spec.md`
- 今回の実装範囲: `spec/phase1.md`
- 配布・起動手順: `docs/runtime_and_distribution.md`

## 開発方針

- まずは最小構成で動くものを作る
- 全文検索アプリとして独立させる
- 既存のファイル名検索ツールとは分離する
- 将来の拡張を見越して責務分離する
  - `api/`
  - `services/`
  - `extractors/`
  - `db/`
  - `models/`

## メモ

- Tailscale 経由でアクセスする場合も、公開インターネットには出さない
- ファイル操作系はサーバが動いているマシン側で実行される前提

## 今回の実装範囲

現時点では、以下を実装しています。

- 対象ファイルは `.md` / `.json` / `.txt` / `.pdf` / `.docx` / `.xlsx` / `.pptx` / `.msg`
- 画像ファイルはファイル名のみ検索対象にできる
- FastAPI バックエンド
- React + Vite フロントエンド
- SQLite FTS5 による全文検索
- 検索時に指定した `フルパス + 階層数 + 対象拡張子` を対象にしたオンデマンドインデックス更新
- `mtime + size` ベースの差分更新
- 本文抽出の並列実行によるインデックス高速化
- 同一の `フルパス + 階層数 + 対象拡張子 + 除外キーワード` に対して、一定時間以内なら再走査を省略するキャッシュ
- Google 風の最小 UI

今回は以下を実装していません。

- OCR
- Excalidraw / draw.io
- インターネット公開向けの認証・防御

## ディレクトリ構成

```text
backend/
  app/
    api/
    db/
    extractors/
    models/
    services/
  requirements.txt
  run.py
frontend/
  src/
    api/
    components/
    styles/
spec/
```

## 起動手順

起動方法は 2 通りあります。

- 開発用の一括起動: `start_dev.sh`
- 配布先向けの直接起動: `backend/run.py`

最小の起動方法:

```bash
cd /path/to/Local-fulltext-search
./start_dev.sh
```

このスクリプトの既定値:

- Backend bind: `0.0.0.0:8079`
- Frontend build: `frontend/dist` を生成
- App URL: `http://127.0.0.1:8079/` または `http://<host>:8079/`
- 起動前に `8079` を使用中なら停止してから起動

この方法は開発用です。  
`start_dev.sh` は `npm install` / `npm run build` を使うため、Node.js / npm が必要です。

必要なら環境変数で上書きできます。

```bash
BACKEND_HOST=0.0.0.0 BACKEND_PORT=8079 ./start_dev.sh
```

同一オリジン配信のため、フロントエンドはバックエンドと同じ URL から配布されます。  
別端末で動かす場合は、その端末から到達できる `BACKEND_HOST` または実ホスト名 / IP でアクセスします。

## 配布運用

会社PCなどでフロントエンドのビルド環境を用意できない運用を想定し、`frontend/dist/` はリポジトリに含めて配布します。  
そのため、配布先で Node.js / npm がなくても、Python 環境があればバックエンド起動だけで画面を開けます。

配布先で必要な前提:

- Python 3 が入っていること
- `pip install -r backend/requirements.txt` が 1 回実行できること
- `frontend/dist/` が clone / pull した内容に含まれていること

配布先で不要なもの:

- Node.js
- npm
- フロントエンドの再ビルド

### 1. バックエンド

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Windows の場合:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

`python run.py` の既定値:

- API: `http://127.0.0.1:8079`
- Health check: `http://127.0.0.1:8079/api/health`

バインドアドレスを変更する場合:

```bash
SEARCH_APP_HOST=0.0.0.0 SEARCH_APP_PORT=8079 python run.py
```

Windows PowerShell:

```powershell
$env:SEARCH_APP_HOST="0.0.0.0"
$env:SEARCH_APP_PORT="8079"
python run.py
```

### 1-1. 配布先での最短起動手順

フロントエンドのビルド環境がない端末では、`frontend/dist/` をそのまま使って FastAPI から配信します。

初回のみ:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

起動コマンド:

```powershell
cd backend
$env:SEARCH_APP_HOST="127.0.0.1"
$env:SEARCH_APP_PORT="8079"
.venv\Scripts\python.exe run.py
```

別PCから同一ネットワーク経由で開きたい場合:

```powershell
cd backend
$env:SEARCH_APP_HOST="0.0.0.0"
$env:SEARCH_APP_PORT="8079"
.venv\Scripts\python.exe run.py
```

起動後のアクセス先:

- ローカルPCで使う場合: `http://127.0.0.1:8079/`
- 別端末から使う場合: `http://<このPCのIPアドレス>:8079/`

### 2. フロントエンドのビルド

```bash
cd frontend
npm install
npm run build
```

Windows でも同じです。

生成物:

- `frontend/dist/`

通常はこの生成物を FastAPI がそのまま配布します。  
配布先で Node.js / npm がない場合は、この手順は不要です。  
開発中に API 接続先だけ変えたい場合は、ビルド時に次のように指定できます。

```bash
VITE_API_BASE_URL=http://mac-mini:8079 npm run build
```

指定しない場合、フロントエンドは同一オリジンの `/api/...` を参照します。

注意:

- `start_dev.sh` の既定 bind は `0.0.0.0:8079`
- `python run.py` の既定 bind は `127.0.0.1:8079`
- どちらも既定ポートは `8079`

### 3. 使い方

1. 検索語を入力する
2. 検索対象フォルダのフルパスを入力する
3. 階層数を入力する
4. 必要ならハンバーガーメニューから `インデックス更新間隔(分)` を変更する
5. 必要ならハンバーガーメニューから `対象拡張子` を選ぶ
6. `Search` を実行する

検索時の動作:

- 指定した `フルパス + 階層数` の組み合わせに対応するインデックスがなければ作成する
- 既存インデックスがあり、前回更新から設定時間以内なら再走査しない
- 設定時間を超えていれば差分更新してから検索する

`階層数` の意味:

- `0`: 指定フォルダ直下のファイルを対象
- `1`: 指定フォルダ直下 + 1階層下までを対象
- `2`: 指定フォルダ直下 + 2階層下までを対象

`フォルダ選択` について:

- フロントから `フォルダ選択` を押すと、サーバを動かしているマシン側でネイティブのフォルダ選択ダイアログを開く
- macOS と Windows を対象にしている
- GUI が使えない環境では、フルパスを直接コピペする

`対象拡張子` について:

- 現在選択できるのは `.md`, `.json`, `.txt` のみ
- デフォルトはすべて選択
- ハンバーガーメニュー内で変更できる

## 他端末での復旧

このリポジトリだけで、新しい端末にアプリ本体を復旧できます。  
ただし、検索対象の実ファイル群そのものは別途その端末または到達可能な共有先に存在している必要があります。

復旧時の前提:

- Python 3 が入っていること
- 検索対象のフォルダに、その端末から実際にアクセスできること
- 初回起動時はネットワーク越しに Python 依存取得ができること
- `frontend/dist/` がリポジトリに含まれていること

復旧手順:

1. リポジトリを clone する
2. `cd backend` に移動する
3. `python -m venv .venv` を実行する
4. `.venv` の Python で `pip install -r requirements.txt` を実行する
5. 必要なら `SEARCH_APP_HOST` / `SEARCH_APP_PORT` を設定して `.venv\Scripts\python.exe run.py` で起動する
6. 画面を開いて、検索対象フォルダのフルパスと階層数を入力して `Search` を 1 回実行する
7. その検索時に DB が作成され、対象ファイルのインデックスが順次作られる

DB について:

- DB ファイルは配布していない
- バックエンド起動時に `data` ディレクトリが自動作成される
- スキーマはアプリ起動時に自動作成される
- 既定の DB パスは `backend/data/search.db` ではなく、バックエンドのカレントディレクトリ基準の `data/search.db`
- `backend/run.py` を `backend/` で起動した場合は `backend/data/search.db` に作られる
- 保存先を変えたい場合は `SEARCH_APP_DATA_DIR` と `SEARCH_APP_DB_NAME` で上書きできる

例:

```bash
cd backend
SEARCH_APP_DATA_DIR=/path/to/app-data SEARCH_APP_DB_NAME=search.db python run.py
```

復旧できるもの:

- アプリ本体のコード
- 空の DB とスキーマ
- 対象ファイルを再走査して作る検索インデックス

復旧できないもの:

- 以前の DB にだけ入っていた検索キャッシュ
- 元ファイルが存在しない検索データ
- その端末から到達できない共有パスの内容

## API 概要

- `POST /api/folders/pick`
- `GET /api/index/status`
- `GET /api/index/failed-files`
- `GET /api/search`
- `POST /api/search`

### `GET /api/search`

必須:

- `q`
- `full_path`
- `index_depth`

任意:

- `refresh_window_minutes`
- `regex_enabled`
- `types`
- `exclude_keywords`
- `limit`
- `offset`

### `POST /api/search`

- 外部アプリ連携では、こちらを推奨
- JSON body で受けるので、Windows の UNC パスや日本語パスを扱いやすい
- パラメータは `GET /api/search` と同じ

例:

```json
{
  "q": "見積",
  "full_path": "\\\\vss45\\一行課\\資料",
  "index_depth": 2,
  "refresh_window_minutes": 60,
  "regex_enabled": false,
  "types": ".md,.json,.txt,.pdf,.docx,.xlsx,.pptx,.msg",
  "exclude_keywords": "node_modules\n.git",
  "limit": 20,
  "offset": 0
}
```

### `POST /api/folders/pick`

- サーバ側でネイティブのフォルダ選択ダイアログを開く
- 返り値は `full_path`

## 実装メモ

- パス処理は `pathlib` を使用
- 保存時は正規化したパスを `as_posix()` で保持
- 差分更新は `mtime` と `size` で判定
- 削除ファイルは DB から自動削除
- DB にはフォルダ登録設定ではなく、`フルパス + 階層数 + 対象拡張子 + 除外キーワード` 単位の内部ターゲットキャッシュを保存
- FTS5 は `file_segments` と連動するトリガで更新

## 外部アプリ連携

他アプリから本アプリを呼び出す場合は、UI 用 URL を開くより、バックエンド API を直接呼ぶ方が扱いやすいです。

- 推奨: `POST /api/search`
- ブラウザや手動確認向け: `GET /api/search`

理由:

- `full_path` に Windows の UNC パスをそのまま載せやすい
- クエリ文字列の組み立てやエスケープを気にしなくてよい
- 将来、呼び出し元が増えても仕様を固定しやすい

### UI をフォルダ指定付きで開く

画面を開くだけでよい場合は、次のクエリ文字列で初期値を渡せます。

- `q`
- `full_path`
- `index_depth` 省略時は `5`

`q` と `full_path` の両方があると、初回表示時に自動で検索を実行します。

例:

```text
http://127.0.0.1:8079/?q=見積&full_path=%2FUsers%2Fmine%2FDocuments&index_depth=2
```

Windows で UNC パスを渡す場合も、URL に入れるときは必ず URL エンコードしてください。

### Windows の UNC パスについて

たとえば次のようなパスを渡せます。

```text
\\vss45\一行課\資料
```

ただし成立条件は次の通りです。

- バックエンドが動いているマシンから、その共有パスに実際にアクセスできること
- Windows の共有を使うなら、通常はバックエンドも Windows 側で動かすこと
- 呼び出し元では URL を手書き連結せず、HTTP クライアントの JSON 送信機能を使うこと

macOS や Linux でバックエンドを動かしている場合、`\\server\share\...` をそのまま解決できるとは限りません。  
その場合は、OS 側で共有をマウントしたローカルパスを渡してください。

### 連携例

JavaScript / TypeScript:

```ts
await fetch("http://127.0.0.1:8079/api/search", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    q: "見積",
    full_path: String.raw`\\vss45\一行課\資料`,
    index_depth: 2,
    refresh_window_minutes: 60,
    regex_enabled: false,
    types: ".md,.json,.txt,.pdf,.docx,.xlsx,.pptx,.msg",
    exclude_keywords: "node_modules\n.git",
    limit: 20,
    offset: 0,
  }),
});
```

PowerShell:

```powershell
$body = @{
  q = "見積"
  full_path = "\\vss45\一行課\資料"
  index_depth = 2
  refresh_window_minutes = 60
  regex_enabled = $false
  types = ".md,.json,.txt,.pdf,.docx,.xlsx,.pptx,.msg"
  exclude_keywords = "node_modules`n.git"
  limit = 20
  offset = 0
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8079/api/search" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## 注意

- 現在のドキュメントはコードを正として更新しています
- 以前の「フォルダ登録ベース」の記述は現行実装とは一致しません
- VPN 経由で使う場合、フロントエンドは `mac-mini` などアクセス元で解決できるホスト名で API を参照する必要があります
