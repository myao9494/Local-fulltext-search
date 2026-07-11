# ローカル全文検索 - ランチャーアプリ仕様書

## 1. 概要
本アプリケーションは、ローカル全文検索システムのバックエンドを利用し、デスクトップ上でいつでも呼び出し可能な高速検索インターフェース（ランチャー）を提供します。MacのSpotlightやRaycastのような操作感を目指します。

## 2. コア機能
- **グローバルホットキー**: `Command + Option` (Mac)、`Windows + Alt` (Windows Flet)、または `Shift` の2回押下 (Windows WPF) で表示/非表示を切り替える。
- **SpotlightスタイルUI**: 画面中央にフローティング表示される、枠のないスタイリッシュな検索バー。
- **リアルタイム検索**: 入力と同時にバックエンドへ問い合わせを行い、結果を動的に表示。
- **結果アクション（全ネイティブランチャー）**:
    - 検索結果タイトル相当のクリック: `LAUNCHER_WEB_BASE_URL` を基準に、ファイルは `/api/fullpath?path=...`、フォルダは `/?path=...` を開く。
    - `Finderで開く`: Web アプリと同じ `/api/files/open-location` を使い、ファイルの場合は親フォルダ、フォルダの場合はそのフォルダを開く。
    - `フォルダを開く`: `LAUNCHER_WEB_BASE_URL` を基準に `/?path=...` を開く。
- **gantt メモ追加（Flet/PyObjC/WPF版）**:
    - ランチャー表示中に `Tab` を押すと検索画面とメモ画面を切り替える。
    - メモ画面では 1 行目を `text`、2 行目以降を `memo` として `LAUNCHER_GANTT_API_BASE_URL/tasks` へ POST する。
    - `start_date` は当日 00:00:00、`end_date` は翌日 00:00:00、`progress` は `0.1`、`kind_task` は `1` とする。
    - 名前欄とメモ欄の`Enter`は入力を継続し、送信しない。送信は送信ボタンのクリック、または送信ボタンへフォーカスした状態の`Enter`だけで行う。
    - 送信成功後は入力をクリアして名前欄へ戻り、ランチャーを表示したまま連続登録できる。`Escape`は検索画面へ戻る。
    - `parent` ID は Web アプリの設定ドロワーにある `gantt parent` で保存した共有設定を、送信直前に読み込んで使用する。
- **オートハイド**:
    - 実行完了（ファイル起動）時に自動的に非表示。
    - ウィンドウ外をクリック（フォーカス喪失）した際に自動的に非表示。

## 3. デザイン仕様 (`AGENTS.md` 準拠)
- **テーマ**: ダークモード (`#0f172a` ベース)
- **視覚効果**: 
    - **Glassmorphism**: 背景に強いブラー (`backdrop-filter: blur(20px)`) をかけ、背後のウィンドウが透ける高級感を演出。
    - **カードデザイン**: WebアプリのUIを踏襲し、スニペット（本文の抜粋）やメタデータを含むリッチな結果表示。
- **配置**: macOS 版はマウスカーソルが存在するディスプレイの中央に表示。Flet 版は Flet の `window.center()` に従って中央表示する。

## 4. 技術スタック
- **GUIフレームワーク**: macOS では PyObjC / Cocoa `NSPanel`。Windowsでは発行済みWPF版を優先し、未発行時はFlet版をフォールバックとして利用する。
- **バックエンド連携**: 既存の FastAPI サーバーに HTTP で接続。macOS 検索は `/api/search`、その他 OS の高速検索は `/api/search/indexed` を使い、アクセス数更新に `/api/search/click`、保存場所表示に `/api/files/open-location` を利用する。
- **グローバルキー監視**: macOS では `CGEventTap` の HID レベル監視を優先して modifier flags を監視し、作成できない場合は session レベルへフォールバックする。補助的に Cocoa `NSEvent` の monitor と `CGEventSourceFlagsState` の watchdog polling も使い、`Command + Option` を検出する。Windows WPF版はWin32低レベルキーボードフックでShiftの押下・解放だけを監視し、Flet版とLinux版は `pynput` を利用する。
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
├── windows/          # Windows WPF版、環境構築・発行スクリプト
└── assets/           # アイコン等の静的ファイル
```

## 6. 現在の実装
- `launcher_app.main` から OS に応じたランチャーを起動する。macOS では仮想デスクトップ対応の Cocoa `NSPanel` を使う。
- `backend/run.py` または `start_dev.sh` でバックエンドを起動すると、`SEARCH_APP_LAUNCHER_AUTOSTART=1` によりランチャーも子プロセスとして自動起動する。
- Web フロントの「ランチャー」ページから、起動・停止・再起動・状態確認・ログ確認を行える。
- **検索のプラットフォーム別挙動**:
    - **macOS**: `/api/search` を使い、登録済みフォルダを検索時に順次更新する (`skip_refresh=false`, `search_all_enabled=false`)。
    - **その他 OS**: `/api/search/indexed` を使い、更新チェックをスキップして既存インデックスのみから高速に検索する。
- 検索結果タイトル相当のクリックは `LAUNCHER_WEB_BASE_URL` を基準に、ファイルでは `/api/fullpath?path=...`、フォルダでは `/?path=...` を既定ブラウザで開く。
- `GUI`ボタンは外部8001ではなく、`LAUNCHER_API_BASE_URL`を基準に8079の検索Web画面を開く。
- ファイル結果を開いた場合は Web アプリと同じく `/api/search/click` でアクセス数を更新する。
- `Finderで開く` / `保存場所` は Web アプリと同じく `/api/files/open-location` を呼ぶ。フォルダ、パスコピー、ganttリンク、ganttメモ関連UIはFlet/PyObjC/WPF版で提供する。
- macOS では `NSWindowCollectionBehaviorCanJoinAllSpaces` により、アクティブな仮想デスクトップ上へ表示する。
- macOS ではスリープ直前にホットキー押下状態をクリアし、復帰後に `CGEventTap`、watchdog polling、Cocoa のグローバル/ローカルイベント monitor を張り直す。
- macOS では表示のたびに `CanJoinAllSpaces` / `FullScreenAuxiliary` / `Stationary` / `Transient` と `NSStatusWindowLevel` を再適用し、現在の Space 上で前面表示する。
- Windows / Linux の Flet 版では、再表示時に `center`、`to_front`、検索欄 `focus` を順に実行し、検索結果の再描画後も検索欄へフォーカスを戻す。また、再表示時には検索欄 of テキストをすべて選択状態（全選択）にして、すぐに新しいキーワードを入力できるようにする。Windows では検索欄フォーカス中の単独 `Enter` を IME 変換確定として扱い、検索結果起動には使わない。ただし、上下矢印キーで検索結果を選択した直後の `Enter` は結果起動として扱い、IME ガードをバイパスする。テキスト入力が行われるとこのフラグはリセットされ、通常の IME 確定動作に戻る。Flet 側の Enter イベントが失われた場合に備え、ランチャー表示中かつ検索画面または gantt メモ画面の単独 `Enter` は `pynput` のグローバルキー監視でも補助的に拾うが、Windows の検索欄フォーカス中は横取りしない（矢印ナビゲーション直後を除く）。さらに、ウィンドウの表示（前面化）および非表示（最小化）のタイミングで、pynput のキー押下・イベント検出状態を明示的にリセットし、Enterキーのリリースイベント取りこぼしによる無反応バグを防止する。


## 7. OS 別パーミッション・注意事項

### macOS
- **アクセシビリティ許可**: グローバルホットキーを有効にするため、起動元のターミナル/アプリに「システム設定 > プライバシーとセキュリティ > アクセシビリティ」の許可が必要。
- **入力監視許可**: `CGEventTap` による安定した検出のため、必要に応じて起動元のターミナル/アプリに「システム設定 > プライバシーとセキュリティ > 入力監視」の許可を追加する。
- **管理者権限**: 不要。

### Windows
- **管理者権限**: 不要。WPF版とFlet版はいずれもWin32のユーザーレベルフック (`SetWindowsHookEx`) を使用する。WPF版はイベントを遮断せずShiftの2回押下だけを判定する。
- **UAC 昇格ウィンドウ**: Flet版の`pynput`とWPF版の低レベルキーボードフックは、Windowsのセキュリティ境界を越える入力監視を保証しない。
- **ウイルス対策ソフト**: Flet版のキーボードフックや、single-file版の自己展開が検知対象になる場合がある。会社環境ではWPF通常版とコード署名を優先する。
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
- `LAUNCHER_WEB_BASE_URL`: primary openに使う外部アプリの既存OpenハブURL。既定値は `http://127.0.0.1:8001`。このリポジトリは8001を起動・停止・再実装しない。
- `LAUNCHER_GANTT_API_BASE_URL`: メモ画面からタスクを作成する gantt API。既定値は `http://localhost:8000/api`。
- `LAUNCHER_GANTT_PARENT`: Web 共有設定の取得に失敗した場合だけ使う gantt parent ID のフォールバック。既定値は `0`。
- `LAUNCHER_SEARCH_LIMIT`: ランチャーに表示する検索結果数。既定値は `8`。
- `LAUNCHER_REQUEST_TIMEOUT`: API タイムアウト秒数。既定値は `5.0`。
- `SEARCH_APP_LAUNCHER_AUTOSTART`: バックエンド起動時にランチャーも起動するか。`backend/run.py` と `start_dev.sh` では既定で `1`。
- `SEARCH_APP_WPF_LAUNCHER_PATH`: Windows WPF版EXEを標準の発行先以外へ配置する場合の絶対パス。指定された実在ファイルを最優先する。
- `SEARCH_APP_LAUNCHER_LOG_NAME`: ランチャーログファイル名。既定値は `launcher.log`。

通信・ログ:
- ランチャーから `LAUNCHER_API_BASE_URL` へのローカル HTTP 通信では、会社環境の `HTTP_PROXY` / `HTTPS_PROXY` による誤転送を避けるためプロキシを使用しない。
- 起動設定、API リクエスト先、HTTP エラー、検索失敗の詳細は `backend/launcher.log` に出力する。バックエンド側に届いた API は `backend/backend.log` にも出力される。

関連する Web オープン先:
- ファイル: `${LAUNCHER_WEB_BASE_URL}/api/fullpath?path=<encoded full_path>`
- フォルダ: `${LAUNCHER_WEB_BASE_URL}/?path=<encoded folder_path>`

## 9. 今後の課題（プロトタイプ後に検討）
- ネオン調のグロー効果などの装飾。
- 検索履歴の保持。
- コマンド実行機能。
- システムトレイ常駐とバックエンド同時起動。
## 10. Windows WPF版

Windowsでは `launcher/windows/` のWPF版を優先する。ホットキーはShiftを400ms以内に2回押して離す操作とし、間に別キーが入った場合は判定をリセットする。入力イベントは遮断せず、競合する可能性がある `RegisterHotKey` は使用しない。検索ウィンドウは
非表示のたびに破棄し、次回表示時に再生成する。これにより仮想デスクトップを
切り替えた後も、ホットキーを押した側のデスクトップにウィンドウを生成する。

配布物はself-containedフォルダ版を標準、single-file版を携帯版とする。発行方法は
`launcher/windows/README.md` を参照する。

WPF版はmacOSネイティブ版の操作仕様に合わせ、gantt検索チェック、Tabでのメモ画面切替、名前・メモ・送信・キャンセル、共有parent取得、結果のパスコピー・保存場所・フォルダ・ganttリンク、GUIボタン、上下キー循環選択を提供する。Windowsの性能仕様に従い、gantt未選択時は `/api/search/indexed`、gantt選択時は `/api/search` を使用する。

検索UIのHWNDは表示する仮想デスクトップに合わせて再生成するが、検索文字列はアプリプロセス側に退避して復元し、再表示時に全選択する。WPF初期版の背景は半透明パネルであり、Windows DWM/Acrylicによる背景ブラーは未実装とする。

`start_windows.bat` はWPFを直接起動せず、`SEARCH_APP_LAUNCHER_AUTOSTART=1` でバックエンドへ起動を委ねる。バックエンドは通常版、single-file版、Python/Flet版の順に選び、子プロセスを管理する。
