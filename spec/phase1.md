# Phase 1 Spec

## 今回の目的

全文検索Webアプリの土台を作り、最小限の対象ファイルに対して検索できる状態を完成させる。

## 今回の対象

### 対応ファイル
- `.md`
- `.json`
- `.txt`

### 今回は対象外
- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.msg`
- `.excalidraw`
- `.drawio`
- `.drawio.svg`
- OCR

## 必須要件

### 実行環境
- Backend: Python + FastAPI
- Frontend: React + Vite
- Search: SQLite FTS5
- macOS / Windows 両対応
- 開発は macOS 前提
- Windows でもデバッグしやすい構成
- `pathlib` を使う
- 文字列連結でパスを作らない

### 利用形態
- 基本はローカル利用
- 必要に応じて Tailscale VPN 経由で私的アクセス
- インターネット公開しない
- アプリ独自認証は必須ではない
- バインドアドレスは設定可能にする
  - `127.0.0.1`
  - `0.0.0.0`

### 検索時指定
- 検索時に対象フォルダのフルパスを指定する
- 検索時に階層数を指定する
- 事前のフォルダ登録 UI は持たない
- 必要ならフォルダ選択ダイアログでフルパス入力を補助する

### 差分更新
差分判定は以下で行う。

- `mtime`
- `size`

更新ルール:
- 新規ファイル → 追加
- 更新ファイル → 再抽出して更新
- 削除ファイル → 削除

### 更新省略
- 同一の `フルパス + 階層数` に対して、前回更新から一定時間以内なら再走査しない
- 既定は 60 分
- この時間は UI のハンバーガーメニューから変更できる

### 対象拡張子
- ハンバーガーメニューから対象拡張子を選択できる
- Phase 1 で表示するのは `.md`, `.json`, `.txt` のみ
- 既定はすべて選択

## API

### `GET /api/search`
パラメータ:
- `q`
- `full_path`
- `index_depth`
- `refresh_window_minutes`
- `types`
- `limit`
- `offset`

### `POST /api/folders/pick`
- サーバ側でネイティブのフォルダ選択ダイアログを開く
- 返り値は `full_path`

### `GET /api/index/status`
以下を返す:
- 最終更新日時
- 総ファイル数
- エラー件数
- 実行中フラグ

## UI

### トップ画面
- 中央にアプリ名
- 大きな検索ボックス
- 検索対象フォルダのフルパス入力
- 階層数入力
- Enter で検索
- 検索ボタン
- ハンバーガーメニューへの導線

### 結果画面
- 上部に検索ボックス
- 結果一覧
- 各結果に以下を表示
  - ファイル名
  - パス
  - スニペット
  - ファイル種別
  - 更新日時

### ハンバーガーメニュー
- インデックス更新間隔(分)の設定
- 対象拡張子の選択
- 状態表示

## DBテーブル

### targets
- `id`
- `full_path`
- `index_depth`
- `last_indexed_at`
- `created_at`
- `updated_at`

### files
- `id`
- `target_id`
- `full_path`
- `normalized_path`
- `depth`
- `file_name`
- `file_ext`
- `mtime`
- `size`
- `indexed_at`
- `last_error`

### file_segments
- `id`
- `file_id`
- `segment_type`
- `segment_label`
- `content`

### FTS
- `file_segments` と連携する FTS5 テーブル

## 完了条件

1. 検索時に `フルパス + 階層数` を指定できる
2. `.md`, `.json`, `.txt` をインデックスできる
3. 差分更新できる
4. 一定時間以内の更新は省略できる
5. 全文検索できる
6. Google風の最小UIで検索できる
7. macOS / Windows のパス差異を吸収できる
8. バインドアドレスを設定できる
9. README に起動手順がある

## 備考

この Phase 1 ドキュメントは現行コードに合わせて更新している。  
以前のフォルダ登録中心の記述は、現在の実装では採用していない。

VPN 経由利用では、現行コードは `0.0.0.0:8081` と `0.0.0.0:5173` での待受を前提にできる。  
フロントエンドは `mac-mini` を `allowedHosts` に含めている。
