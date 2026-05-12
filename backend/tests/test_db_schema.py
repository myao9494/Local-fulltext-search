"""
検索系クエリの性能を支える補助インデックスを検証する。
"""

import sqlite3
from pathlib import Path

from app.db.schema import initialize_schema


def test_initialize_schema_creates_file_segments_lookup_index(tmp_path: Path) -> None:
    """
    file_id + segment_type の結合に使う補助インデックスを作成する。
    """
    connection = sqlite3.connect(tmp_path / "search.db")
    try:
        initialize_schema(connection)

        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'file_segments'
            ORDER BY name
            """
        ).fetchall()

        assert [row[0] for row in rows] == ["idx_file_segments_file_id_segment_type"]
    finally:
        connection.close()


def test_initialize_schema_creates_search_filter_indexes(tmp_path: Path) -> None:
    """
    source_type とパス条件での絞り込みを支える補助インデックスを作成する。
    """
    connection = sqlite3.connect(tmp_path / "search.db")
    try:
        initialize_schema(connection)

        file_indexes = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'files'
            ORDER BY name
            """
        ).fetchall()
        target_indexes = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'targets'
            ORDER BY name
            """
        ).fetchall()

        assert "idx_files_source_type_normalized_path" in [row[0] for row in file_indexes]
        assert "idx_targets_enabled_source_type_full_path" in [row[0] for row in target_indexes]
    finally:
        connection.close()


def test_initialize_schema_creates_scheduler_daily_runs_table(tmp_path: Path) -> None:
    """
    Windows 定期スケジュールの同一枠二重起動を防ぐ実行記録テーブルを作成する。
    """
    connection = sqlite3.connect(tmp_path / "search.db")
    try:
        initialize_schema(connection)

        columns = connection.execute("PRAGMA table_info(scheduler_daily_runs);").fetchall()

        assert [row[1] for row in columns] == ["id", "run_key", "scheduled_time", "started_at"]
    finally:
        connection.close()
