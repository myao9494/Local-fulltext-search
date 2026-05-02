"""
ランチャーの実行時設定を環境変数から読み取る。
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LauncherConfig:
    """
    バックエンド接続先とランチャー検索の既定値を保持する。
    """

    api_base_url: str = "http://127.0.0.1:8079"
    web_base_url: str = "http://localhost:8001"
    search_limit: int = 8
    request_timeout: float = 5.0

    @classmethod
    def from_env(cls) -> "LauncherConfig":
        """
        環境変数を読み取り、未指定時はローカル開発用の既定値を返す。
        """
        return cls(
            api_base_url=os.environ.get("LAUNCHER_API_BASE_URL", cls.api_base_url),
            web_base_url=os.environ.get("LAUNCHER_WEB_BASE_URL", cls.web_base_url),
            search_limit=_read_int("LAUNCHER_SEARCH_LIMIT", cls.search_limit),
            request_timeout=_read_float("LAUNCHER_REQUEST_TIMEOUT", cls.request_timeout),
        )


def _read_int(name: str, default: int) -> int:
    """
    正の整数の環境変数だけを採用する。
    """
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _read_float(name: str, default: float) -> float:
    """
    正の小数の環境変数だけを採用する。
    """
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default
