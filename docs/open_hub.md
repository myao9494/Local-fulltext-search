# Open/UIハブ（8001）契約

## 責務

本アプリは、検索データ面と結果を開く入口を別プロセス・別ポートに分離する。

| 面 | 既定URL | 責務 |
| --- | --- | --- |
| Search/API | `http://127.0.0.1:8079` | 検索、インデックス、設定、click記録、`open-location`、ランチャー管理 |
| Open/UIハブ | `http://127.0.0.1:8001` | Web UI配信と、検索結果をどう開くかを集約する固定入口 |

ランチャーとWebクライアントは検索に8079を使い、primary openには8001だけを使う。8079から8001へのリダイレクトやプロキシは必須にしない。8001はWeb UIからの相対`/api/*`を内部で8079へ中継するため、ブラウザは8001だけを表示しても検索できる。

## Open契約

### ファイル

```text
GET ${OPEN_HUB_BASE}/api/fullpath?path=<URLエンコード済み絶対パス>
```

8001を動かしているPC上で、指定ファイルまたはフォルダをOS既定アプリで開く。相対パスは422、存在しないパスは404、OS起動失敗は500を返す。成功時は200の短い完了ページを返す。Openハブはループバックアドレスへのbindを既定とし、ブラウザが明示するcross-siteリクエストは拒否する。

### フォルダ検索UI

```text
GET ${OPEN_HUB_BASE}/?path=<URLエンコード済みフォルダ絶対パス>
```

8001がReact SPAを表示する。SPAは`path`を初期検索条件として解釈し、API要求は8001が8079へ中継する。これはExplorer/Finderで保存場所を表示する操作ではない。保存場所操作は従来どおり8079の`POST /api/files/open-location`を使う。

### Web・gantt結果

Web検索結果のURLとgantt結果が持つ外部リンクは、既存仕様どおりそのURLを直接開く。ローカルファイル／フォルダのOpen契約をクライアントごとに分岐させないため、ローカル結果だけが上記の固定パス規則を使う。click記録は8079のままとする。

## 起動と設定

`backend/run.py`、`start_windows.bat`、`start_dev.sh`は8079バックエンドと8001 Openハブを一緒に起動する。Openハブは`backend/run.py`から独立した子プロセスとして管理される。

主な環境変数:

- `SEARCH_APP_HOST` / `SEARCH_APP_PORT`: Search/APIのbind。既定`127.0.0.1:8079`
- `SEARCH_APP_OPEN_HUB_HOST` / `SEARCH_APP_OPEN_HUB_PORT`: Openハブのbind。既定`127.0.0.1:8001`
- `SEARCH_APP_OPEN_HUB_AUTOSTART`: Openハブをバックエンドから起動する。`backend/run.py`は既定で有効
- `SEARCH_APP_OPEN_HUB_API_BASE_URL`: Openハブが内部接続する8079 URL
- `LAUNCHER_API_BASE_URL`: ランチャーのSearch/API URL
- `LAUNCHER_WEB_BASE_URL`: ランチャーのOpenハブURL（互換性のため変数名は維持）
- `VITE_API_BASE_URL`: WebクライアントのSearch/API URL。8001配信時は空文字の相対URLでよい
- `VITE_OPEN_HUB_BASE_URL`: WebクライアントのOpenハブURL

DNSを使わない会社PCの同一端末構成:

```powershell
$env:LAUNCHER_API_BASE_URL="http://127.0.0.1:8079"
$env:LAUNCHER_WEB_BASE_URL="http://127.0.0.1:8001"
start_windows.bat
```

別端末へ公開する場合はOpen操作を実行させるPCでOpenハブを起動し、`SEARCH_APP_OPEN_HUB_HOST=0.0.0.0`を明示する。クライアント側の2つのbase URLはDNS名ではなく固定IPへ差し替える。ネットワーク公開時はファイアウォールとアクセス制御を別途設けること。

## 障害の切り分け

- 8079停止: 検索・設定・click・保存場所表示と、8001から中継されるWeb UIのAPI操作が失敗する。8001のヘルス確認とローカル`/api/fullpath`は独立して動作できる。
- 8001停止: 8079への検索APIは動作するが、ランチャーのprimary openと8001のWeb UIは失敗する。
- ヘルス確認: 8079は`/api/health`、8001は`/_open_hub/health`。8001の`/api/health`は8079への中継確認にも使える。
