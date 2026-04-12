<!--
インデックス作成・検索のパフォーマンス最適化について記載する。
-->

# パフォーマンス最適化

## 概要

インデックス作成と検索の速度向上のために、以下の最適化を実施している。

## インデックス作成

### バッチ commit

ファイルごとの `commit()` を廃止し、100件ごとのバッチcommitに変更。  
ディスク I/O を大幅に削減し、インデックス作成速度を 2〜5倍向上させる。

- `_upsert_file()` 内での commit を削除
- `_record_file_error()` 内での commit を削除
- `_index_target()` 側で 100件ごとに commit

### os.scandir ベースの走査

`Path.rglob("*")` の代わりに `os.scandir` による再帰走査を使用。

メリット:

- 除外キーワードに一致するディレクトリは再帰しないため、不要な走査を省ける
- `rglob` より 2〜3倍高速

### 除外キーワードの最適化

除外キーワードを `frozenset` に変換し、完全一致の判定を `O(1)` にした。

- ASCII キーワード: set によるルックアップ
- 非ASCII キーワード: サブストリング検索（事前分離）
- ASCII トークン分割: set の共通集合で判定

### 削除のバッチ化

`executemany` による 1行ずつの DELETE を、`IN` 句による500件ごとのバッチ DELETE に変更。

## SQLite PRAGMA 設定

`connection.py` で以下のPRAGMAを設定している:

| PRAGMA | 値 | 効果 |
|:-------|:---|:-----|
| `journal_mode` | WAL | 読み書きの並行性向上 |
| `foreign_keys` | ON | 外部キー制約の有効化 |
| `synchronous` | NORMAL | WAL併用時に安全かつ高速（書き込み 30〜50% 向上） |
| `cache_size` | -64000 | キャッシュを 64MB に拡大 |
| `temp_store` | MEMORY | 一時テーブルをメモリ上に配置 |
| `mmap_size` | 268435456 | 256MB のメモリマップ読み取り |

## 検索

### FTS CTE 統合

FTS5 検索で `COUNT(*)` と結果データの取得を1つのクエリに統合。  
以前は同じ CTE を2回実行していたが、`filtered` CTE + サブクエリ COUNT で1回に削減。

### 正規表現検索のイテレータ化

`fetchall()` の代わりにカーソルイテレータを使用。  
全件をメモリに展開せず、逐次処理してメモリ使用量を抑制。

## DB 接続共有

`app.state.db_connection` にアプリケーション起動時の接続を保持し、  
リクエストごとの再接続オーバーヘッドを削減。  
FastAPI の `Depends` を通じて共有接続を注入する。

## ステータス管理の簡素化

`_update_status()` から不要な `SELECT * FROM index_runs` を削除し、  
SQL の `COALESCE` に全てのデフォルト処理を委ねる。
