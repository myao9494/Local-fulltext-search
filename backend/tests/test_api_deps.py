"""
API依存性注入のDB接続ライフサイクルを検証する。
リクエストごとに新しい接続を返し、終了時にクローズすることを担保する。
"""

import sqlite3
from pathlib import Path

import pytest

from app.api.deps import get_db_connection
from app.config import settings


def test_get_db_connection_yields_fresh_connection_each_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    DB接続依存性は呼び出しごとに別インスタンスを返す。
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_name", "deps.db")

    dependency_a = get_db_connection()
    dependency_b = get_db_connection()
    connection_a = next(dependency_a)
    connection_b = next(dependency_b)

    assert connection_a is not connection_b
    assert connection_a.execute("SELECT 1").fetchone()[0] == 1
    assert connection_b.execute("SELECT 1").fetchone()[0] == 1

    dependency_a.close()
    dependency_b.close()

    with pytest.raises(sqlite3.ProgrammingError):
        connection_a.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        connection_b.execute("SELECT 1")
