"""
ランチャーアプリのコマンドラインエントリーポイント。
"""

import platform

from launcher_app.config import LauncherConfig


def main() -> None:
    """
    環境変数から設定を読み取り、OS に適したランチャーを起動する。
    """
    config = LauncherConfig.from_env()
    if platform.system() == "Darwin":
        from launcher_app.ui.native_mac import run_native_mac_app

        run_native_mac_app(config)
    else:
        from launcher_app.ui.app import run_app

        run_app(config)


if __name__ == "__main__":
    main()
