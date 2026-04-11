# local-fulltext-search

ローカルPCおよび必要に応じて Tailscale VPN 経由で私的利用する、全文検索専用の Web アプリです。

## 目的

- ファイル名検索ではなく、**ファイル内容の全文検索**に特化する
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
- Full-text search: SQLite FTS5

## 対応予定ファイル

### Phase 1
- `.md`
- `.json`
- `.txt`

### 将来対応
- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.msg`
- `.excalidraw`
- `.drawio`
- `.drawio.svg`

## 仕様書

- 全体仕様: `spec/product_spec.md`
- 今回の実装範囲: `spec/phase1.md`

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

Phase 1 として、以下のみ実装しています。

- 対象ファイルは `.md` / `.json` / `.txt`
- FastAPI バックエンド
- React + Vite フロントエンド
- SQLite FTS5 による全文検索
- 検索時に指定した `フルパス + 階層数` を対象にしたオンデマンドインデックス更新
- `mtime + size` ベースの差分更新
- 同一の `フルパス + 階層数` に対して、一定時間以内なら再走査を省略するキャッシュ
- Google 風の最小 UI

今回は以下を実装していません。

- PDF / Office / Outlook / Excalidraw / draw.io
- OCR
- ファイル名検索
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

最小の起動方法:

```bash
cd /path/to/Local-fulltext-search
./start_dev.sh
```

このスクリプトの既定値:

- Backend bind: `0.0.0.0:8081`
- Frontend bind: `0.0.0.0:5173`
- Frontend API base: `http://mac-mini:8081`
- 起動前に `8081` と `5173` を使用中なら停止してから起動

必要なら環境変数で上書きできます。

```bash
FRONTEND_API_HOST=mac-mini BACKEND_HOST=0.0.0.0 FRONTEND_HOST=0.0.0.0 ./start_dev.sh
```

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

デフォルトの起動先:

- API: `http://0.0.0.0:8081`
- Health check: `http://127.0.0.1:8081/api/health`

バインドアドレスを変更する場合:

```bash
SEARCH_APP_HOST=0.0.0.0 SEARCH_APP_PORT=8081 python run.py
```

Windows PowerShell:

```powershell
$env:SEARCH_APP_HOST="0.0.0.0"
$env:SEARCH_APP_PORT="8081"
python run.py
```

### 2. フロントエンド

```bash
cd frontend
npm install
npm run dev
```

Windows でも同じです。

デフォルトの表示先:

- Frontend: `http://0.0.0.0:5173`

API の接続先を変更する場合:

```bash
VITE_API_BASE_URL=http://mac-mini:8081 npm run dev -- --host 0.0.0.0 --port 5173
```

Vite は `mac-mini` を `allowedHosts` に追加済みです。  
VPN 経由では通常、次のようにアクセスします。

- Frontend: `http://mac-mini:5173/`
- Backend API: `http://mac-mini:8081/`

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
- `1`: 1階層下のファイルを対象
- `2`: 2階層下のファイルを対象

`フォルダ選択` について:

- フロントから `フォルダ選択` を押すと、サーバを動かしているマシン側でネイティブのフォルダ選択ダイアログを開く
- macOS と Windows を対象にしている
- GUI が使えない環境では、フルパスを直接コピペする

`対象拡張子` について:

- 現在選択できるのは `.md`, `.json`, `.txt` のみ
- デフォルトはすべて選択
- ハンバーガーメニュー内で変更できる

## API 概要

- `POST /api/folders/pick`
- `GET /api/index/status`
- `GET /api/search`
- `POST /api/search`

### `GET /api/search`

必須:

- `q`
- `full_path`
- `index_depth`

任意:

- `refresh_window_minutes`
- `types`
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
  "types": ".md,.json,.txt",
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
- DB にはフォルダ登録設定ではなく、`フルパス + 階層数` 単位の内部ターゲットキャッシュを保存
- FTS5 は `file_segments` と連動するトリガで更新

## 外部アプリ連携

他アプリから本アプリを呼び出す場合は、UI 用 URL を開くより、バックエンド API を直接呼ぶ方が扱いやすいです。

- 推奨: `POST /api/search`
- ブラウザや手動確認向け: `GET /api/search`

理由:

- `full_path` に Windows の UNC パスをそのまま載せやすい
- クエリ文字列の組み立てやエスケープを気にしなくてよい
- 将来、呼び出し元が増えても仕様を固定しやすい

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
await fetch("http://127.0.0.1:8081/api/search", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    q: "見積",
    full_path: String.raw`\\vss45\一行課\資料`,
    index_depth: 2,
    refresh_window_minutes: 60,
    types: ".md,.json,.txt",
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
  types = ".md,.json,.txt"
  limit = 20
  offset = 0
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8081/api/search" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## 注意

- 現在のドキュメントはコードを正として更新しています
- 以前の「フォルダ登録ベース」の記述は現行実装とは一致しません
- VPN 経由で使う場合、フロントエンドは `mac-mini` などアクセス元で解決できるホスト名で API を参照する必要があります
