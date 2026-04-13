"""
API依存性注入のDB接続ライフサイクルを検証する。
アプリケーション共有接続を使い回し、リクエスト終了時にクローズしないことを担保する。
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.deps import get_db_connection
from app.config import settings


def test_get_db_connection_returns_shared_connection_from_app_state() -> None:
    """
    app.state.db_connection に保持された共有接続をそのまま返す。
    """
    mock_request = MagicMock()
    shared_connection = MagicMock(spec=sqlite3.Connection)
    mock_request.app.state.db_connection = shared_connection

    result = get_db_connection(mock_request)

    assert result is shared_connection
