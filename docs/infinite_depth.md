# 階層の無限大（未入力時の無限大化）およびUIコンパクト化に関する仕様

## 目的
ユーザーがデフォルトで階層制限なくすべての深さのファイルを検索できるようにするため、階層指定が未入力（空欄）の場合は無限大として扱う。
また、検索結果の一覧表示領域を広げるため、階層入力UIを1段目（フォルダ指定行の右側）へインライン化し、説明テキストはホバー時のみツールチップ（`title` 属性）として表示することで、縦方向のスペースを節約し画面全体の高さをコンパクトにする。

## 詳細設計

### 1. バックエンド API & モデルの変更
- クエリパラメータ `index_depth` をオプショナルに変更: `index_depth: int | None = Query(default=None, ge=0, le=99999)`
- 検索リクエストモデル `SearchQueryParams` の `index_depth` をオプショナルに変更: `index_depth: int | None = Field(default=None, ge=0, le=99999)`
- サービス層（`search_service.py` および `index_service.py`）で、`index_depth` が `None` の場合は内部的な無限大値 `99999` を使用する。

### 2. フロントエンド UI & クライアントの変更
- `launchParams.ts` のデフォルト値を `""`（空文字）とする。
- `SearchBar.tsx` のプレースホルダーを `"無制限"` に変更。
- 従来の2段目にあった `.filter-group.depth-group` を廃止し、1段目の `.path-picker-row.top-path-picker` 内に `.depth-field-inline` を追加して階層入力をインライン配置とする。
- 説明テキスト「0=直下のみ、空欄=無制限」は、入力欄および親コンテナの `title` 属性に設定し、マウスホバー時のみツールチップとして表示させる。
- `app.css` に `.depth-field-inline` クラスのスタイル定義（`display: inline-flex; align-items: center; gap: 8px; margin-left: 8px; flex-shrink: 0;`）を追加する。
- API クライアント `frontend/src/api/client.ts` で、`indexDepth` が空文字のときは `index_depth` をリクエストに含めない。

### 3. デスクトップランチャーの変更
- `launcher/src/launcher_app/api/client.py` 内の `index_depth` の値を `99999` に設定、あるいはパラメータから省略。

## 構成・データフロー

```
[フロントエンド (未入力/空欄)] ──► index_depth は送信しない
                                    │
                                    ▼
                             [バックエンド] ──► None を検知 ──► 内部値 99999 (無制限) を適用
                                                                    │
                                                                    ▼
                                                             [SQLite 走査] (max_depth=99999)
```
