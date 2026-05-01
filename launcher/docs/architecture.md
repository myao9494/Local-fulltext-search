# ランチャーアプリ - アーキテクチャ設計

## 1. 起動モデル (一体型常駐)
バックエンドサーバー（FastAPI）の起動プロセスの一部として、または並列してランチャープロセスを起動します。

### 構成要素
- **Server Process**: SQLite 検索エンジンと API サービスを提供。
- **Launcher Process (Flet)**: UIを提供し、システムトレイに常駐。
- **Global Listener Thread**: OSレベルのキーイベントを監視し、Fletウィンドウの表示/非表示を制御。

## 2. システム連携図

```mermaid
graph LN
    subgraph "OS (Windows/Mac)"
        HK[Global Hotkey: Opt+Cmd]
        Mouse[Mouse Cursor Position]
    end

    subgraph "Launcher App (Flet)"
        Tray[System Tray Icon]
        UI[Search Window]
        Client[API Client]
        Listener[Hotkey Listener Thread]
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
    UI -->|Open File| OS_App[OS File Opener]
```

## 3. 主要な技術的ポイント

### グローバルショートカットの実現
Flet単体ではウィンドウフォーカス時しかキーを取得できないため、別スレッドで `pynput` 等を使用してリスナーを回します。
```python
# 概念コード
def on_activate():
    # Fletウィンドウを表示し、フォーカスを当てる
    page.window_visible = True
    page.window_to_front()
    page.update()

listener = keyboard.GlobalHotKeys({
    '<cmd>+<alt>': on_activate
})
listener.start()
```

### ウィンドウのスタイリング
Spotlight感を出すためのFlet設定:
- `page.window_frameless = True`
- `page.window_transparent = True`
- `page.window_always_on_top = True`
- `page.window_center()` (ただしマウス位置に基づく調整が必要)

### バックエンドとの通信
初期実装では `LAUNCHER_API_BASE_URL` (既定値 `http://127.0.0.1:8079`) の既存APIを HTTP で呼び出します。

- 検索: `POST /api/search`
- アクセス数更新: `POST /api/search/click`
- 保存場所表示: `POST /api/files/open-location`

ランチャーは高速応答を優先するため、検索時に `search_all_enabled=true` と `skip_refresh=true` を指定し、既存インデックスだけを軽く読む挙動を基本にします。将来的にパフォーマンスやオフライン起動が必要な場合は、同一プロセス内でのDB直接参照を検討します。

### UI とテスト境界
Flet 依存は `launcher_app.ui` に閉じ込め、以下の処理は標準ライブラリだけでテストできるように分離します。

- `launcher_app.api.client`: 既存 FastAPI との JSON 通信
- `launcher_app.services.file_actions`: OS 標準アプリ起動・Finder/Explorer 表示
- `launcher_app.services.hotkeys`: OS ごとのホットキー定義と `pynput` 遅延読み込み
