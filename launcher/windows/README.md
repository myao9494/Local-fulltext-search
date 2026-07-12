# Windows WPF ランチャー

Windows標準APIと.NET標準機能だけで動く、Windows x64向けランチャーです。

- グローバルショートカット: 設定に応じて `Shift` を400ms以内に素早く2回押して離す、または `Windows + Alt`
- 同じショートカットまたは `Esc`: 非表示
- フォーカス喪失: 非表示
- 表示するたびにWPFウィンドウを作り直すため、ショートカットを押した現在の仮想デスクトップへ表示
- ウィンドウ再生成時も検索文字列を保持し、再表示時に全選択
- 多重起動防止

WPF版はmacOSネイティブ版の操作仕様に合わせ、検索欄右側の拡張子フィルタ、gantt検索、タスク名・メモ・送信・キャンセル、共有parent取得、パスコピー、保存場所、フォルダ、ganttリンク、GUIボタン、上下キー循環選択を提供します。`Tab` / `Shift + Tab` は「検索欄 → 拡張子欄 → タスク名 → メモ → 送信 → 検索欄」を循環し、送信後のTabでは検索画面を表示します。`.py`、`.bat`、`.exe`、`.lnk` は8001のOpenハブを経由せず、親フォルダをcurrent directoryとして直接起動します。Windowsの検索性能仕様に従い、gantt未選択時は既存インデックスだけを検索します。

WPF初期版の背景は半透明ネイビーパネルとドロップシャドウです。Windows DWM/Acrylicによる背景ブラーは未実装です。

## 発行

開発用Windows PCでは、最初に.NET 8 SDKをユーザー領域へ導入します。管理者権限とVisual Studioは不要です。

```powershell
.\launcher\windows\setup-dotnet.ps1
```

新しいPowerShellを開き、次を実行します。

```powershell
.\launcher\windows\publish.ps1
```

発行中は起動中の `LocalSearchLauncher.exe` を終了してください。発行スクリプトは古い成果物の混入を防ぐため、対象の出力フォルダを削除してから作り直します。

`publish/folder` が会社PC向けの第一候補、`publish/single-file` が携帯版です。会社PC側にSDKや.NETランタイムは不要です。

### Gitでの配布

会社PCでビルドを行わずに起動できるよう、`launcher/windows/publish/folder` と `launcher/windows/publish/single-file` の発行成果物は Git の追跡対象です。ランチャーの C# コード・プロジェクト設定・同梱アセットを変更したら、開発PCで `publish.ps1` を実行し、両方の発行先をソース変更と同じコミットで push してください。

`bin/`・`obj/`、Python の仮想環境、依存関係キャッシュはビルド中間物またはローカル依存のため、Gitには含めません。会社PCではリポジトリを取得後に `start_windows.bat` を実行し、追跡済みの `publish/folder/LocalSearchLauncher.exe` を使用します。

発行スクリプトは各出力フォルダを作り直すため、以前のPDBやDLLが配布物へ混入しません。single-file版はEXE 1個、通常版は.NETランタイムを含む複数ファイルになります。single-file版は実行時にネイティブライブラリを一時ディレクトリへ展開するため、社内EDRとの相性では通常版を優先してください。

`start_windows.bat` はバックエンドを起動し、バックエンドのランチャー管理機能が `launcher\windows\publish\folder\LocalSearchLauncher.exe` を優先して子プロセスとして起動します。なければsingle-file版、どちらもなければ従来のPython/Flet版を起動します。この経路に統一することで、Web画面/APIから状態確認・停止・再起動できます。

EXEを別フォルダへ配置する場合は、`SEARCH_APP_WPF_LAUNCHER_PATH` に絶対パスを指定します。この指定は標準の発行先より優先されます。

通常の大文字入力で誤発火しないよう、1回目と2回目の間にShift以外のキーを押すと判定をリセットします。キー入力自体は遮断しません。`RegisterHotKey` は使用しないため、他アプリのグローバルショートカット登録とは競合しません。

バッチを再実行すると、強制終了された旧バックエンドから残った `LocalSearchLauncher` プロセスを先に終了してから、新しいバックエンド配下で起動し直します。これにより多重起動防止Mutexだけが残り、管理APIが誤って停止状態を示すことを避けます。
