# Phase 1 Spec

## 今回の目的

全文検索Webアプリの土台に加え、主要な文書フォーマットを検索できる状態を完成させる。

## 今回の対象

### 対応ファイル
- `.md`
- `.json`
- `.txt`
- `.xml`
- `.excalidraw`
- `.dio`
- `.excalidraw.md`
- `.dio.svg`
- `.pdf`
- `.docx`
- `.xlsx`
- `.xlsm`
- `.pptx`
- `.msg`
- 画像系はファイル名のみ検索対象

### 今回は対象外
- OCR

## 必須要件

### 実行環境
- Backend: Python + FastAPI
- Frontend: React + Vite
- Search: SQLite FTS5
- 日本語など空白で区切られない本文は補助 bi-gram インデックスで部分一致検索を補完する
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
- 既存インデックス全体を対象に検索する場合は `full_path` を空にできる
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
- 同一の `フルパス + 階層数 + 対象拡張子 + 除外キーワード` に対して、前回更新から一定時間以内なら再走査しない
- 既定は 60 分
- この時間は UI のハンバーガーメニューから変更できる
- ただし、旧インデックスに日本語補助 bi-gram セグメントが不足している場合は再走査して補完する

### 対象拡張子
- ハンバーガーメニューから対象拡張子を選択できる
- 本文抽出対象とファイル名のみ対象の拡張子を選択できる
- 本文抽出対象 / ファイル名のみ対象の追加拡張子を保存できる
- 既定はすべて選択
- 検索バー側には、インデックス対象設定とは独立した検索結果絞り込み用の拡張子入力を持つ

## API

### `GET /api/search`
パラメータ:
- `q`
- `full_path`
- `search_all_enabled`
- `index_depth`
- `refresh_window_minutes`
- `regex_enabled`
- `index_types`
- `types`
- `exclude_keywords`
- `date_field`
- `sort_by`
- `sort_order`
- `created_from`
- `created_to`
- `limit`
- `offset`

### `POST /api/folders/pick`
- サーバ側でネイティブのフォルダ選択ダイアログを開く
- 返り値は `full_path`

### `POST /api/search/indexed`
- `q`
- `folder_path`
- 既存 DB だけを使って検索する
- 対象フォルダ配下を深さ無制限で検索する
- 再インデックスは行わない

### `GET /api/index/status`
以下を返す:
- 最終更新日時
- 総ファイル数
- エラー件数
- 実行中フラグ
- 中止要求フラグ

### `GET /api/index/settings` / `PUT /api/index/settings`
- 除外キーワード
- 同義語リスト
- インデックス対象拡張子
- 本文抽出対象の追加拡張子
- ファイル名のみ対象の追加拡張子

### `GET /api/index/failed-files`
以下を返す:
- 取得失敗したファイルのパス
- ファイル名
- エラーメッセージ
- 最終失敗日時

### `GET /api/index/targets` / `DELETE /api/index/targets`
- 実際にインデックス済みファイルを含むフォルダ一覧を返す
- 選択したフォルダ配下のインデックスと失敗履歴をまとめて削除できる

### `POST /api/index/cancel`
- 実行中インデックスへ中止要求を送る

### `POST /api/index/reset`
- DB を空の初期状態へ戻す

### `POST /api/search/click`
- 検索結果オープン時のアクセス数を 1 件加算する

## UI

### トップ画面
- 画面上部のタブで `検索` と `インデックス済みフォルダ` を切り替える
- 検索対象フォルダのフルパス入力
- `全データベース` 切り替え
- 階層数入力
- 検索ボックス
- 正規表現トグル
- 検索拡張子フィルタ入力
- 日付種別 + 期間フィルタ
- 並び替え条件
- インデックス状態表示
- インデックス中止ボタン
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
  - 作成日または更新日
  - アクセス数
  - フルパスのコピー導線
  - 親フォルダを開くリンク

### ハンバーガーメニュー
- インデックス更新間隔(分)の設定
- 対象拡張子の選択
- 追加拡張子の登録 / 削除
- 除外キーワードの設定
- 同義語リストの設定
- 既定検索フォルダの設定
- 失敗ファイル一覧
- データベース初期化
- 状態表示

### インデックス済みフォルダ画面
- フルパス部分一致で絞り込みできる
- 絞り込み結果に対する一括選択ができる
- インデックス済みファイル数と最終インデックス日時を表示する
- 選択したフォルダ配下のインデックスを削除できる

## DBテーブル

### targets
- `id`
- `full_path`
- `exclude_keywords`
- `index_depth`
- `selected_extensions`
- `last_indexed_at`
- `created_at`
- `updated_at`

### files
- `id`
- `full_path`
- `normalized_path`
- `file_name`
- `file_ext`
- `mtime`
- `created_at`
- `click_count`
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
- 本文セグメントに加え、必要に応じて日本語部分一致用の `cjk_bigram` セグメントも保持する

### index_runs
- `id`
- `is_running`
- `cancel_requested`
- `last_started_at`
- `last_finished_at`
- `last_error`
- `total_files`
- `error_count`

### failed_files
- `id`
- `normalized_path`
- `file_name`
- `error_message`
- `last_failed_at`

## 完了条件

1. 検索時に `フルパス + 階層数` を指定できる
2. `.md`, `.json`, `.txt`, `.xml`, `.excalidraw`, `.dio`, `.excalidraw.md`, `.dio.svg`, `.pdf`, `.docx`, `.xlsx`, `.xlsm`, `.pptx`, `.msg` をインデックスできる
3. 差分更新できる
4. 一定時間以内の更新は省略できる
5. 全文検索と一部ファイルのファイル名検索ができる
6. `お寿司` を含む本文に対して `寿司` でもヒットする
7. Google風の最小UIで検索できる
8. macOS / Windows のパス差異を吸収できる
9. バインドアドレスを設定できる
10. README に起動手順がある

## 備考

この Phase 1 ドキュメントは現行コードに合わせて更新している。  
以前のフォルダ登録中心の記述は、現在の実装では採用していない。

現在の通常配布では、ビルド済みの `frontend/dist/` を FastAPI から同一オリジン配信する。  
そのため、配布先の通常運用では Vite 開発サーバの起動は必須ではない。

開発時に Vite を使う場合は、`vite.config.ts` の設定により `5173` 番ポートで起動する。  
VPN 経由利用などで別端末から開発用フロントエンドへ接続する場合は、必要に応じて `allowedHosts` を調整する。
