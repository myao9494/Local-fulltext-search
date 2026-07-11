# 外部Open/UIハブ（8001）連携契約

## 所有権と前提

8001番で動作するOpen/UIハブは、このリポジトリとは別の必要アプリが提供する。本リポジトリは8001のサーバーを実装・起動・停止・再起動・監視・プロキシしない。`start_windows.bat`、`start_dev.sh`、`backend/run.py`が管理するのは8079のSearch/APIとランチャーだけである。

8001アプリが停止している場合、検索結果を開く要求は接続エラーになってよい。8079へフォールバックしたり、8079から8001へリダイレクト／プロキシしたりして挙動を置き換えない。

| 接続先 | 所有者 | このリポジトリの用途 |
| --- | --- | --- |
| `http://127.0.0.1:8079` | Local Fulltext Search | 検索、インデックス、設定、click記録、`open-location`、Web検索画面 |
| `http://127.0.0.1:8001` | 外部Openハブアプリ | 検索結果を開く既存エンドポイントの呼び出し先 |

## 変更してはいけない既存エンドポイント

ランチャーとWebクライアントは、従来どおり次のURLを既定ブラウザで開くだけとする。8001側の具体的な処理、応答、画面、内部連携は外部アプリの責務であり、このリポジトリでは再実装しない。

```text
ファイル: ${OPEN_HUB_BASE}/api/fullpath?path=<URLエンコード済みfull_path>
フォルダ: ${OPEN_HUB_BASE}/?path=<URLエンコード済みfolder_path>
```

- `OPEN_HUB_BASE`の既定値は`http://127.0.0.1:8001`
- ランチャーでは`LAUNCHER_WEB_BASE_URL`で差し替える
- Webビルドでは`VITE_OPEN_HUB_BASE_URL`で差し替える
- 末尾スラッシュはクライアント側で正規化し、path規則は変更しない
- web結果とganttリンクは既存仕様どおり、それぞれが持つURL／APIを使用する
- click記録とExplorer/Finderの`open-location`は8079のまま維持する
- ランチャーの`GUI`ボタンも8079の検索Web画面を開き、8001へは送らない

## DNSなし環境

同一PCでの既定設定:

```powershell
$env:LAUNCHER_API_BASE_URL="http://127.0.0.1:8079"
$env:LAUNCHER_WEB_BASE_URL="http://127.0.0.1:8001"
start_windows.bat
```

外部Openハブが別PCにある場合だけ、`LAUNCHER_WEB_BASE_URL`と`VITE_OPEN_HUB_BASE_URL`をそのPCの固定IPへ変更する。ホスト名やDNSを必須にしない。

## 障害の切り分け

- 8079停止: 検索・設定・click記録・保存場所表示が失敗する。外部8001アプリの状態は変更しない。
- 8001停止: primary openが接続エラーになる。8079の検索機能は継続する。
- 起動スクリプトは8001のプロセスやポートへ一切操作を行わない。
