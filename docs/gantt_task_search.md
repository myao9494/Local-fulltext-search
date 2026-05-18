# gantt タスク検索

## 目的
gantt アプリのタスク内容を、通常のローカルファイル検索とは分離した任意選択の検索対象として扱う。

## API 連携
- 既定の取得先は `http://localhost:8000/api/tasks`。
- バックエンド設定 `SEARCH_APP_GANTT_API_BASE_URL` で Base URL を変更できる。
- 認証なしの JSON API として扱い、レスポンスは配列または `tasks` / `data` / `items` 配下の配列をタスク一覧として読む。

## 検索仕様
- 検索 API は `include_gantt_tasks: true` が指定されたときだけ gantt API を呼び出す。
- `local` / `web` の検索結果に gantt タスク結果を追加する。
- `include_gantt_tasks` が未指定または `false` の既定検索には gantt タスクを混ぜない。
- タスク JSON の文字列・数値項目を平文化し、空白区切りの検索語を AND 条件で照合する。
- 検索結果は `source_type: "gantt"`、`full_path: "gantt://tasks/{id}"` として返す。
- gantt タスクのタイトルクリック時は、バックエンド経由で `POST /tasks/{task_id}/open-input` を呼び出す。
- タスク JSON に `link` / `url` / `href` / `input_url` / `external_url` がある場合だけ、結果アクションに「ganttのリンクを開く」を表示する。

## UI
- Web 版検索バーに `gantt` の追加チェックを置く。
- ランチャーは macOS ネイティブ版、Windows/Flet 版ともに `gantt` チェックを有効にした時だけ通常検索に gantt タスク結果を追加する。
