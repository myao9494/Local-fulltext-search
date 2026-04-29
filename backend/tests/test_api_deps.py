"""
API依存性注入のDB接続ライフサイクルを検証する。
リクエストごとに SQLite 接続を開閉し、並列リクエスト間で同一接続を共有しないことを担保する。
"""

import sqlite3
from pathlib import Path

import pytest

from app.api.deps import get_db_connection
from app.config import settings


def test_get_db_connection_opens_and_closes_request_scoped_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    依存性注入はリクエストごとに新しい接続を返し、利用後にクローズする。
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_name", "request.db")

    dependency = get_db_connection()
    connection = next(dependency)

    assert isinstance(connection, sqlite3.Connection)
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")

    with pytest.raises(StopIteration):
        next(dependency)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_get_db_connection_returns_distinct_connections_per_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    同時リクエストで同じ sqlite3.Connection インスタンスを共有しない。
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_name", "request.db")

    first_dependency = get_db_connection()
    second_dependency = get_db_connection()
    first = next(first_dependency)
    second = next(second_dependency)

    try:
        assert first is not second
    finally:
        for dependency in (first_dependency, second_dependency):
            with pytest.raises(StopIteration):
                next(dependency)
