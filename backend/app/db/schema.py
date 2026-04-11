from sqlite3 import Connection


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_path TEXT NOT NULL,
        index_depth INTEGER NOT NULL,
        last_indexed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(full_path, index_depth)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER NOT NULL,
        full_path TEXT NOT NULL,
        normalized_path TEXT NOT NULL UNIQUE,
        depth INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        file_ext TEXT NOT NULL,
        mtime REAL NOT NULL,
        size INTEGER NOT NULL,
        indexed_at TEXT NOT NULL,
        last_error TEXT,
        FOREIGN KEY(target_id) REFERENCES targets(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS file_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        segment_type TEXT NOT NULL,
        segment_label TEXT NOT NULL,
        content TEXT NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS file_segments_fts
    USING fts5(content, segment_label, content='file_segments', content_rowid='id');
    """,
    """
    CREATE TABLE IF NOT EXISTS index_runs (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        is_running INTEGER NOT NULL DEFAULT 0,
        last_started_at TEXT,
        last_finished_at TEXT,
        last_error TEXT,
        total_files INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    INSERT INTO index_runs (id, is_running, total_files, error_count)
    VALUES (1, 0, 0, 0)
    ON CONFLICT(id) DO NOTHING;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS file_segments_ai AFTER INSERT ON file_segments BEGIN
        INSERT INTO file_segments_fts(rowid, content, segment_label)
        VALUES (new.id, new.content, new.segment_label);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS file_segments_ad AFTER DELETE ON file_segments BEGIN
        INSERT INTO file_segments_fts(file_segments_fts, rowid, content, segment_label)
        VALUES ('delete', old.id, old.content, old.segment_label);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS file_segments_au AFTER UPDATE ON file_segments BEGIN
        INSERT INTO file_segments_fts(file_segments_fts, rowid, content, segment_label)
        VALUES ('delete', old.id, old.content, old.segment_label);
        INSERT INTO file_segments_fts(rowid, content, segment_label)
        VALUES (new.id, new.content, new.segment_label);
    END;
    """,
]


def initialize_schema(connection: Connection) -> None:
    if _needs_schema_reset(connection):
        connection.execute("DROP TABLE IF EXISTS file_segments_fts;")
        connection.execute("DROP TABLE IF EXISTS file_segments;")
        connection.execute("DROP TABLE IF EXISTS files;")
        connection.execute("DROP TABLE IF EXISTS targets;")
        connection.execute("DROP TABLE IF EXISTS folders;")
        connection.execute("DROP TABLE IF EXISTS index_runs;")
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.commit()


def _needs_schema_reset(connection: Connection) -> bool:
    target_columns = _get_columns(connection, "targets")
    legacy_folder_columns = _get_columns(connection, "folders")
    file_columns = _get_columns(connection, "files")

    if not target_columns and not legacy_folder_columns and not file_columns:
        return False

    expected_target_columns = {"id", "full_path", "index_depth", "last_indexed_at", "created_at", "updated_at"}
    expected_file_columns = {
        "id",
        "target_id",
        "full_path",
        "normalized_path",
        "depth",
        "file_name",
        "file_ext",
        "mtime",
        "size",
        "indexed_at",
        "last_error",
    }
    if legacy_folder_columns:
        return True
    return target_columns != expected_target_columns or file_columns != expected_file_columns


def _get_columns(connection: Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row[1]) for row in rows}
