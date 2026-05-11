<!--
Flet の Windows/Linux デスクトップクライアントをオフライン配布するための配置場所。
-->

# Flet View オフライン配置

Windows の `start_windows.bat` は完全オフライン起動を前提に、ここへ配置された Flet View を使います。

配置方法はどちらか一方です。

1. 展開済みディレクトリを置く
   - Windows: `launcher/vendor/flet-view/windows/flet.exe`
   - Linux: `launcher/vendor/flet-view/linux/flet`
2. アーカイブを置く
   - Windows: `launcher/vendor/flet-view/flet-view-windows.zip`
   - Linux: `launcher/vendor/flet-view/flet-view-linux.tar.gz`

アーカイブ配置の場合、初回起動時に `launcher/.offline_cache/flet-view/` へ展開され、`FLET_VIEW_PATH` が自動設定されます。

このリポジトリでは Flet を `0.84.0` に固定しています。Windows では Flet の GitHub Releases から `v0.84.0` の `flet-windows.zip` を取得し、`flet-view-windows.zip` にリネームしてこのディレクトリへ置いてください。

会社のオフライン端末へ持ち込む前に、このディレクトリへ保存してからリポジトリごと配布してください。
