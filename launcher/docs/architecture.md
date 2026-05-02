# ランチャーアプリ - アーキテクチャ設計

## 1. 起動モデル (一体型常駐)
バックエンドサーバー（FastAPI）の起動プロセスの一部として、または並列してランチャープロセスを起動します。

### 構成要素
- **Server Process**: SQLite 検索エンジンと API サービスを提供。
- **Launcher Process**: macOS では Cocoa `NSPanel`、その他 OS では Flet UI を提供する。
- **Launcher Manager**: FastAPI lifespan で初期化され、ランチャー子プロセスの起動・停止・再起動・ログ取得を担当する。
- **Global Listener**: macOS では Cocoa `NSEvent`、その他 OS では `pynput` で表示/非表示を制御する。

## 2. システム連携図

```mermaid
graph LR
    subgraph "OS (Windows/Mac)"
        HK[Global Hotkey: Opt+Cmd]
        Mouse[Mouse Cursor Position]
    end

    subgraph "Launcher App"
        Tray[System Tray Icon]
        UI[Search Window]
        Client[API Client]
        Listener[Hotkey Listener]
    end

    subgraph "Backend Manager"
        LM[Launcher Manager]
        Log[launcher.log]
    end

    subgraph "Backend (Existing)"
        API[FastAPI / Search Endpoint]
        DB[(SQLite / FTS5)]
    end

    HK --> Listener
    Listener -->|Trigger Show/Hide| UI
    Mouse -->|Determine Position| UI
    UI -->|Search Query| Client
    Client -->|HTTP/JSON| API
    API --> DB
    UI -->|Open Web-compatible URL| Browser[Default Browser / localhost:8001]
    UI -->|Open Location| API
    LM -->|Spawn / Stop / Restart| UI
    LM -->|Tail Logs| Log
```

## 3. 主要な技術的ポイント

### macOS の表示モデル
macOS では Flet の最小化・復帰が Spaces と相性が悪いため、PyObjC / Cocoa の `NSPanel` を使います。

- `NSWindowCollectionBehaviorCanJoinAllSpaces` でアクティブな仮想デスクトップに表示する。
- `NSEvent` の modifier flags 監視で `Option + Command` を検出する。
- ボーダーレスでも入力できるよう `canBecomeKeyWindow()` / `canBecomeMainWindow()` を `True` にした `LauncherPanel` を使う。

### バックエンドとの通信
初期実装では `LAUNCHER_API_BASE_URL` (既定値 `http://127.0.0.1:8079`) の既存APIを HTTP で呼び出します。

- 検索: `POST /api/search`
- アクセス数更新: `POST /api/search/click`
- 保存場所表示: `POST /api/files/open-location`
- ランチャー管理: `GET /api/launcher/status`, `POST /api/launcher/start`, `POST /api/launcher/stop`, `POST /api/launcher/restart`
- 検索結果を開く: Web アプリと同じ `http://localhost:8001/api/fullpath?path=...` または `http://localhost:8001/?path=...` を既定ブラウザで開く。

ランチャーは高速応答を優先するため、検索時に `search_all_enabled=true` と `skip_refresh=true` を指定し、既存インデックスだけを軽く読む挙動を基本にします。将来的にパフォーマンスやオフライン起動が必要な場合は、同一プロセス内でのDB直接参照を検討します。

### UI とテスト境界
UI 依存は `launcher_app.ui` に閉じ込め、以下の処理はテストできるように分離します。

- `launcher_app.api.client`: 既存 FastAPI との JSON 通信
- `launcher_app.ui.native_mac`: Web アプリ互換 URL の生成
- `app.services.launcher_service`: バックエンド配下のランチャープロセス管理とログ末尾取得
- `launcher_app.services.file_actions`: OS 標準アプリ起動・Finder/Explorer 表示
- `launcher_app.services.hotkeys`: OS ごとのホットキー定義と `pynput` 遅延読み込み

ランチャー子プロセスの Python は、ランチャー依存関係を入れるプロジェクトルート `.venv` を優先し、存在しない場合のみバックエンド実行中の Python へフォールバックします。
