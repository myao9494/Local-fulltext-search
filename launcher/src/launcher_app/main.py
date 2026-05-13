"""
ランチャーアプリのコマンドラインエントリーポイント。
"""

import logging
import platform
import sys

from launcher_app.config import LauncherConfig
from launcher_app.offline_flet import prepare_flet_view


def configure_logging() -> None:
    """
    ランチャー単体の診断ログを標準出力へ出し、バックエンド起動時は launcher.log に保存させる。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def main() -> None:
    """
    環境変数から設定を読み取り、OS に適したランチャーを起動する。
    """
    configure_logging()
    config = LauncherConfig.from_env()
    logging.getLogger(__name__).info(
        "Launcher starting: platform=%s api_base_url=%s web_base_url=%s timeout=%.1fs limit=%d",
        platform.system(),
        config.api_base_url,
        config.web_base_url,
        config.request_timeout,
        config.search_limit,
    )
    if platform.system() == "Darwin":
        from launcher_app.ui.native_mac import run_native_mac_app

        run_native_mac_app(config)
    else:
        prepare_flet_view()
        from launcher_app.ui.app import run_app

        run_app(config)


if __name__ == "__main__":
    main()
