# 階層の無限大（未入力時の無限大化）およびUIコンパクト化仕様書

## 概要
ファイル検索の最大走査階層（`index_depth`）の入力が空（未入力）である場合、制限なし（無限大、システム内部的には `99999`）と判断する。
また、検索結果の一覧性を高めるため、階層指定UIを2段目の独立グループから1段目のフォルダ指定行へマージし、説明はホバー時のツールチップ表示（`title`属性）へ集約して検索パネルを縦方向にコンパクト化する。

## 変更内容
1. **バックエンド**:
   - `index_depth` を任意（Optional）にし、指定がない（`None`）場合はデフォルト値として `99999`（無制限）を適用する。
   - `index_depth` のバリデーション上限を `128` から `99999` に引き上げる。
   - 対象ファイル:
     - `backend/app/models/search.py`
     - `backend/app/api/search.py`
     - `backend/app/services/search_service.py` (None 時の補完)
     - `backend/app/services/index_service.py` (None 時の補完)

2. **フロントエンド**:
   - `indexDepth` のデフォルト値を空文字 `""` にする。空文字は「無制限」を意味する。
   - API リクエストを送信する際、`indexDepth` が空文字の場合は `index_depth` パラメータを省略する（あるいは `undefined` として送信しない）。
   - UIの階層入力欄を2段目の `depth-group` から削除し、1段目の `path-picker-row` 内に `.depth-field-inline` としてインライン配置する。
   - プレースホルダーを `"無制限"` にし、説明文（「0=直下のみ、空欄=無制限」）は入力欄および親ラッパーの `title` 属性（ツールチップ）としてホバー時のみ表示する。
   - 対象ファイル:
     - `frontend/src/launchParams.ts`
     - `frontend/src/components/SearchBar.tsx`
     - `frontend/src/api/client.ts`
     - `frontend/src/styles/app.css` (`.depth-field-inline` のスタイル定義の追加)

3. **デスクトップランチャー**:
   - ランチャーからの検索リクエストで送信される `index_depth` を `99999` （あるいはパラメータから省略）にする。
   - 対象ファイル:
     - `launcher/src/launcher_app/api/client.py`
