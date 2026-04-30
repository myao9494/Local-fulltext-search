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
- `index_depth` を超える階層には入らないため、浅い検索の無駄な走査を省ける
- 対象拡張子で走査対象を早期に絞り込める
- `rglob` より 2〜3倍高速
- **エントリ名のみで除外判定**: 再帰走査なので親パーツは既にチェック済み。`_is_excluded_name(entry.name, ...)` だけを呼び、フルパスの全パーツチェックを省略

### 本文抽出の並列化

PDF / Office / Outlook の本文抽出は比較的重いため、テキスト抽出だけを `ThreadPoolExecutor` で並列化する。

- ファイル走査と SQLite 書き込みはメインスレッドで直列維持
- 本文抽出だけをワーカースレッドへ委譲
- **ワーカー数**: I/Oバウンドタスクが支配的なため、`min(16, cpu_count * 2)` で上限設定
- SQLite 接続を複数スレッドから同時更新しないため、整合性と速度を両立
- 画像のような本文なしファイルは抽出タスクを作らず、ファイル名メタデータだけを即時登録

### 除外キーワードの最適化

除外キーワードを `frozenset` に変換し、完全一致の判定を `O(1)` にした。

- ASCII キーワード: set によるルックアップ
- 非ASCII キーワード: サブストリング検索（事前分離）
- ASCII トークン分割: set の共通集合で判定

### 削除のバッチ化

`executemany` による 1行ずつの DELETE を、`IN` 句による500件ごとのバッチ DELETE に変更。  
`file_segments` を先に明示的に DELETE してから `files` を削除し、FTS5 トリガーを確実に発火させる。
再インデックス時の削除判定は、現在の検索対象パス、`index_depth`、拡張子フィルタ、除外条件で走査した範囲だけに限定する。  
過去に深い階層、別拡張子、除外中のフォルダまで作成したインデックスは、浅い階層・一部拡張子・子パスで検索や再インデックスをしても対象外として保持する。
親フォルダが検索対象に登録済みで子パスを検索した場合も、削除クリーンアップは子パス配下だけに閉じる。

### failed_file クリアの一括化

ファイルごとの `DELETE FROM failed_files WHERE normalized_path = ?` を廃止。  
インデックス完了後に `_clear_resolved_failed_files()` で一括クリーンアップする。  
こちらも現在の検索対象パス、`index_depth`、拡張子フィルタ、除外条件内だけを掃除し、今回走査していない深い階層や別拡張子、除外中パスの失敗履歴は残す。

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

## SQLite クエリの最適化

### LIKE から範囲クエリへの変換

`normalized_path LIKE '/path/%'` の代わりに、子孫パス用の共通境界ヘルパーで  
`normalized_path >= prefix_start AND normalized_path < prefix_end` を組み立てる。  
B-tree インデックスを活用し、大量レコードの前方一致検索を高速化する。

- 通常パスは `prefix = '/path/'` のように末尾 `/` をそろえる
- ルートパスは `/` や `C:/` を `//` / `C://` にしない
- 上限値は `prefix + U+10FFFF` を使い、ルートディレクトリでも安全に前方一致範囲を表現する
- インデックス作成側と検索側の両方で同じ境界計算を共有する

## 検索

### FTS CTE 統合

FTS5 検索で `COUNT(*)` と結果データの取得を1つのクエリに統合。  
以前は同じ CTE を2回実行していたが、`filtered` CTE + サブクエリ COUNT で1回に削減。

### scoped_files CTE による対象フォルダの前絞り

検索語ごとの `UNION ALL` 分岐それぞれに、同じフォルダ・階層・拡張子・日付条件を繰り返し埋め込むのをやめ、  
先に `scoped_files` CTE で候補ファイルを 1 回だけ絞り込んでから本文 / ファイル名検索へ渡す。

- `files.normalized_path` の範囲条件を 1 回だけ評価できる
- 検索語や同義語が増えても、フォルダ条件のバインド値が乗算で増えない
- 全データベース検索中でもフォルダ指定がある場合、対象配下だけを早めに候補化できる

### file_segments 結合用インデックス

`file_segments(file_id, segment_type)` の補助インデックスを追加し、  
`scoped_files` から本文セグメントや bi-gram セグメントを引く JOIN を高速化する。

- 正規表現検索の `LEFT JOIN file_segments ... segment_type = 'body'`
- ファイル名一致時の本文スニペット取得
- 日本語 bi-gram 検索時の本文セグメント再取得

### 大規模ベンチマーク CLI

300万件級の合成データで検索速度を再現確認したいときは、`backend/benchmark_search.py` を使う。

```bash
PYTHONPATH=$(pwd)/backend uv run --with-requirements backend/requirements.txt \
  python backend/benchmark_search.py \
  --db-path /tmp/local_fulltext_search_benchmark_3m.db \
  --total-files 3000000 \
  --folder-count 300 \
  --target-folder-index 42
```

- `folder-count` を減らすと、1フォルダあたり件数が増えた厳しめの条件を再現できる
- ベンチ生成時は FTS トリガーを止め、投入後に `rebuild` するため、大規模データでも短時間で再生成できる

### 日本語部分一致の補助インデックス

SQLite FTS5 の既定トークナイザでは、日本語の連続文字列が1語として扱われやすく、  
`お寿司` を含む本文に対して `寿司` のような部分語がヒットしにくい。  
そのため、本文セグメントに加えて日本語連続文字列から生成した bi-gram 補助セグメントも保持する。

- 日本語語を含む検索時だけ、通常本文 FTS に加えて補助 bi-gram セグメントも検索する
- 補助セグメントには元本文も残し、ASCII 語との混在 AND 検索を崩さない
- 補助セグメント由来の結果は、元本文からリテラル一致の抜粋を組み立てて表示する
- 旧インデックスに補助セグメントが存在しない場合は、検索時の再走査判定で検知して補完する

### 正規表現検索のイテレータ化

`fetchall()` の代わりにカーソルイテレータを使用。  
全件をメモリに展開せず、逐次処理してメモリ使用量を抑制。

### 段階読み込み

全データベース検索では、初回レスポンスを 50 件に固定し、画面下端へ到達した時だけ次の 50 件を追加取得する。  
これにより、大規模 DB でも「全件取得完了」まで待たずに上位結果を先に表示できる。

- 初回ページは順位付き上位 50 件だけ返す
- `has_more` と `next_offset` で次ページ有無を返す
- スニペットはページ単位で生成し、未表示ページ分は後回しにする

### Obsidian アクセス数の非同期同期

Obsidian sidebar-explorer の `accessCounts` は検索中に毎回合算せず、検索後にバックグラウンドで `files.obsidian_click_count` へ同期する。  
次回検索では DB 保存済みの値を使って SQL の `ORDER BY` だけでアクセス数順を決定する。

- `files.click_count` はアプリ内クリック数
- `files.obsidian_click_count` は外部同期値
- `click_count` 並び替えは両者の合算値で行う

## DB 接続

`lifespan` コンテキストマネージャで起動時にスキーマを初期化する。
API リクエストでは FastAPI の `Depends` を通じてリクエストスコープの接続を作成し、処理後にクローズする。
SQLite の同一接続を複数スレッドへ共有しないことで、並列リクエスト時のトランザクション干渉を避ける。

インデックス中止要求はメモリ上のコントローラに加えて `index_runs.cancel_requested` に保存する。
これにより、スケジューラーの別プロセス・別接続で動くインデックス処理も UI からの中止要求を検知できる。

## ステータス管理の簡素化

`_update_status()` から不要な `SELECT * FROM index_runs` を削除し、  
SQL の `COALESCE` に全てのデフォルト処理を委ねる。

## FTS5 のゴーストレコード防止

`ON DELETE CASCADE` だけでは FTS5 の AFTER DELETE トリガーが発火しない可能性があるため、  
`file_segments` を先に明示的に DELETE してから `files` を削除する。  
これにより FTS5 インデックスの一貫性を保証する。
