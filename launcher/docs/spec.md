# ローカル全文検索 - ランチャーアプリ仕様書

## 1. 概要
本アプリケーションは、ローカル全文検索システムのバックエンドを利用し、デスクトップ上でいつでも呼び出し可能な高速検索インターフェース（ランチャー）を提供します。MacのSpotlightやRaycastのような操作感を目指します。

## 2. コア機能
- **グローバルホットキー**: `Option + Command` (Mac) または `Ctrl + Alt` (Windows) で即座に表示/非表示を切り替え。
- **SpotlightスタイルUI**: 画面中央にフローティング表示される、枠のないスタイリッシュな検索バー。
- **リアルタイム検索**: 入力と同時にバックエンドへ問い合わせを行い、結果を動的に表示。
- **アクション**:
    - 検索結果タイトル相当のクリック: Web アプリと同じ `http://127.0.0.1:8079/api/fullpath?path=...` または `http://127.0.0.1:8079/?path=...` を開く。
    - `Finderで開く`: Web アプリと同じ `/api/files/open-location` を使い、ファイルの場合は親フォルダ、フォルダの場合はそのフォルダを開く。
    - `フォルダを開く`: Web アプリと同じ `http://127.0.0.1:8079/?path=...` を開く。
- **オートハイド**:
    - 実行完了（ファイル起動）時に自動的に非表示。
    - ウィンドウ外をクリック（フォーカス喪失）した際に自動的に非表示。

## 3. デザイン仕様 (`AGENTS.md` 準拠)
- **テーマ**: ダークモード (`#0f172a` ベース)
- **視覚効果**: 
    - **Glassmorphism**: 背景に強いブラー (`backdrop-filter: blur(20px)`) をかけ、背後のウィンドウが透ける高級感を演出。
    - **カードデザイン**: WebアプリのUIを踏襲し、スニペット（本文の抜粋）やメタデータを含むリッチな結果表示。
- **配置**: マウスカーソルが存在するディスプレイの中央に表示。

## 4. 技術スタック
- **GUIフレームワーク**: macOS では PyObjC / Cocoa `NSPanel`。その他 OS では Flet 版をフォールバックとして利用する。
- **バックエンド連携**: 既存の FastAPI サーバーに HTTP で接続。ランチャーの初期実装では `/api/search`, `/api/search/click`, `/api/files/open-location` を利用する。
- **グローバルキー監視**: macOS では `CGEventTap` の HID レベル監視を優先して modifier flags を監視し、作成できない場合は session レベルへフォールバックする。補助的に Cocoa `NSEvent` の monitor と `CGEventSourceFlagsState` の watchdog polling も使い、`Option + Command` を検出する。その他 OS では `pynput` を利用する。
- **スリープ復帰対応**: macOS では `NSWorkspaceWillSleepNotification` / `NSWorkspaceDidWakeNotification` を監視し、復帰時に `CGEventTap` と `NSEvent` monitor を再登録してホットキーを復旧する。
- **仮想デスクトップ復帰**: パネル表示直前に Space 関連の `NSWindowCollectionBehavior`、window level、非アクティブ時の非表示設定を張り直し、長時間放置による App Nap を抑止する。
- **常駐形態**: バックエンドサーバー配下の子プロセスとして起動し、Web フロントの「ランチャー」ページから状態確認・起動・停止・再起動・ログ確認を行う。システムトレイ常駐は未実装。

## 5. フォルダ構成
既存のWebアプリ（React）と分離するため、独立したディレクトリで管理します。
```text
launcher/
├── docs/             # ランチャー専用ドキュメント
│   └── spec.md       # 本仕様書
├── src/              # ソースコード (Python)
│   └── launcher_app/
│       ├── main.py       # エントリーポイント
│       ├── ui/           # Cocoa / Flet UI
│       ├── api/          # バックエンド連携ロジック
│       └── services/     # OS連携・ホットキー監視
├── tests/            # ランチャー専用テスト
└── assets/           # アイコン等の静的ファイル
```

## 6. 現在の実装
- `launcher_app.main` から OS に応じたランチャーを起動する。macOS では仮想デスクトップ対応の Cocoa `NSPanel` を使う。
- `backend/run.py` または `start_dev.sh` でバックエンドを起動すると、`SEARCH_APP_LAUNCHER_AUTOSTART=1` によりランチャーも子プロセスとして自動起動する。
- Web フロントの「ランチャー」ページから、起動・停止・再起動・状態確認・ログ確認を行える。
- 検索は全DB対象 (`search_all_enabled=true`) かつ既存インデックス優先 (`skip_refresh=true`) で実行する。
- 検索結果タイトル相当のクリックは Web アプリと同じ URL (`http://127.0.0.1:8079/api/fullpath?path=...` / `http://127.0.0.1:8079/?path=...`) を既定ブラウザで開く。
- ファイル結果を開いた場合は Web アプリと同じく `/api/search/click` でアクセス数を更新する。
- `Finderで開く` は Web アプリと同じく `/api/files/open-location` を呼ぶ。
- macOS では `NSWindowCollectionBehaviorCanJoinAllSpaces` により、アクティブな仮想デスクトップ上へ表示する。
- macOS ではスリープ直前にホットキー押下状態をクリアし、復帰後に `CGEventTap`、watchdog polling、Cocoa のグローバル/ローカルイベント monitor を張り直す。
- macOS では表示のたびに `CanJoinAllSpaces` / `FullScreenAuxiliary` / `Stationary` / `Transient` と `NSStatusWindowLevel` を再適用し、現在の Space 上で前面表示する。

## 7. OS 別パーミッション・注意事項

### macOS
- **アクセシビリティ許可**: グローバルホットキーを有効にするため、起動元のターミナル/アプリに「システム設定 > プライバシーとセキュリティ > アクセシビリティ」の許可が必要。
- **入力監視許可**: `CGEventTap` による安定した検出のため、必要に応じて起動元のターミナル/アプリに「システム設定 > プライバシーとセキュリティ > 入力監視」の許可を追加する。
- **管理者権限**: 不要。

### Windows
- **管理者権限**: 不要。pynput は Win32 のユーザーレベルフック (`SetWindowsHookEx`) を使用するため、通常のユーザー権限で動作する。
- **UAC 昇格ウィンドウ**: 管理者として実行中のアプリ（タスクマネージャー等）が前面にあるとき、pynput はそのウィンドウのキー入力を捕捉できない。これは Windows のセキュリティ仕様であり回避不可。
- **ウイルス対策ソフト**: pynput はキーボード入力を監視するため、一部のウイルス対策ソフトがキーロガーと誤検知する場合がある。必要に応じてランチャーの実行ファイルを除外設定に追加する。
- **ファイアウォール**: バックエンドが localhost 以外のマシンにある場合は、受信規則の追加が必要。

### Linux
- **pynput 依存**: X11 環境では `xdotool` や `Xlib` が必要な場合がある。Wayland 環境では pynput のグローバルキー監視が動作しない場合がある。
- **管理者権限**: 不要。ただし `/dev/input` へのアクセスにユーザーグループ (`input`) への追加が必要な場合がある。

## 8. 起動方法
```bash
cd launcher
python -m pip install -r requirements.txt
PYTHONPATH=src python -m launcher_app.main
```

`backend/run.py` から自動起動する場合は、ランチャー依存関係も含む `backend/requirements.txt` をバックエンド実行に使う Python 環境へ入れておく。

```bash
cd backend
python -m pip install -r requirements.txt
python run.py
```

環境変数:
- `LAUNCHER_API_BASE_URL`: 接続先 API。既定値は `http://127.0.0.1:8079`。
- `LAUNCHER_WEB_BASE_URL`: Web フロント URL。既定値は `http://127.0.0.1:8079`。
- `LAUNCHER_SEARCH_LIMIT`: ランチャーに表示する検索結果数。既定値は `8`。
- `LAUNCHER_REQUEST_TIMEOUT`: API タイムアウト秒数。既定値は `5.0`。
- `SEARCH_APP_LAUNCHER_AUTOSTART`: バックエンド起動時にランチャーも起動するか。`backend/run.py` と `start_dev.sh` では既定で `1`。
- `SEARCH_APP_LAUNCHER_LOG_NAME`: ランチャーログファイル名。既定値は `launcher.log`。

関連する Web オープン先:
- ファイル: `http://127.0.0.1:8079/api/fullpath?path=<encoded full_path>`
- フォルダ: `http://127.0.0.1:8079/?path=<encoded folder_path>`

## 9. 今後の課題（プロトタイプ後に検討）
- ネオン調のグロー効果などの装飾。
- 検索履歴の保持。
- コマンド実行機能。
- システムトレイ常駐とバックエンド同時起動。
