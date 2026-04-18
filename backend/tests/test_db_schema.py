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
