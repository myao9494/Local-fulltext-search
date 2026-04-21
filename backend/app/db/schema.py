from sqlite3 import Connection


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_path TEXT NOT NULL,
        last_indexed_at TEXT,
        exclude_keywords TEXT NOT NULL DEFAULT '',
        index_depth INTEGER NOT NULL DEFAULT 1,
        selected_extensions TEXT NOT NULL DEFAULT '',
        is_search_target_enabled INTEGER NOT NULL DEFAULT 1,
        indexed_file_count INTEGER NOT NULL DEFAULT 0,
        index_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(full_path)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_path TEXT NOT NULL,
        normalized_path TEXT NOT NULL UNIQUE,
        file_name TEXT NOT NULL,
        file_ext TEXT NOT NULL,
        created_at REAL NOT NULL,
        mtime REAL NOT NULL,
        click_count INTEGER NOT NULL DEFAULT 0,
        size INTEGER NOT NULL,
        indexed_at TEXT NOT NULL,
        last_error TEXT
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
    CREATE INDEX IF NOT EXISTS idx_file_segments_file_id_segment_type
    ON file_segments(file_id, segment_type);
    """,
    """
    CREATE TABLE IF NOT EXISTS index_runs (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        is_running INTEGER NOT NULL DEFAULT 0,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        last_started_at TEXT,
        last_finished_at TEXT,
        last_error TEXT,
        total_files INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    INSERT INTO index_runs (id, is_running, cancel_requested, total_files, error_count)
    VALUES (1, 0, 0, 0, 0)
    ON CONFLICT(id) DO NOTHING;
    """,
    """
    CREATE TABLE IF NOT EXISTS failed_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        normalized_path TEXT NOT NULL UNIQUE,
        file_name TEXT NOT NULL,
        error_message TEXT NOT NULL,
        last_failed_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        start_at TEXT,
        is_enabled INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    """,
    """
    INSERT INTO scheduler_settings (id, start_at, is_enabled, updated_at)
    VALUES (1, NULL, 0, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO NOTHING;
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_paths (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheduler_id INTEGER NOT NULL,
        folder_path TEXT NOT NULL,
        sort_order INTEGER NOT NULL,
        FOREIGN KEY(scheduler_id) REFERENCES scheduler_settings(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduler_paths_unique_order
    ON scheduler_paths(scheduler_id, sort_order);
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_runtime (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        status TEXT NOT NULL DEFAULT 'idle',
        current_path TEXT,
        process_id INTEGER,
        run_token TEXT,
        last_started_at TEXT,
        last_finished_at TEXT,
        last_error TEXT
    );
    """,
    """
    INSERT INTO scheduler_runtime (
        id, status, current_path, process_id, run_token, last_started_at, last_finished_at, last_error
    )
    VALUES (1, 'idle', NULL, NULL, NULL, NULL, NULL, NULL)
    ON CONFLICT(id) DO NOTHING;
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        logged_at TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        folder_path TEXT
    );
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
        _drop_managed_schema_objects(connection)
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    _apply_non_destructive_migrations(connection)
    connection.commit()


def reset_schema(connection: Connection) -> None:
    """
    管理対象の全テーブルと FTS を削除し、空のスキーマを再作成する。
    共有接続を維持したまま DB を初期化したいときに使う。
    """
    _drop_managed_schema_objects(connection)
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    _apply_non_destructive_migrations(connection)
    connection.commit()


def _apply_non_destructive_migrations(connection: Connection) -> None:
    """
    既存DBは可能な限り保持したまま、後方互換な列追加だけを反映する。
    """
    file_columns = _get_columns(connection, "files")
    target_columns = _get_columns(connection, "targets")
    if "click_count" not in file_columns:
        connection.execute("ALTER TABLE files ADD COLUMN click_count INTEGER NOT NULL DEFAULT 0;")
    if "indexed_file_count" not in target_columns:
        connection.execute("ALTER TABLE targets ADD COLUMN indexed_file_count INTEGER NOT NULL DEFAULT 0;")
    if "index_version" not in target_columns:
        connection.execute("ALTER TABLE targets ADD COLUMN index_version INTEGER NOT NULL DEFAULT 0;")
    if "is_search_target_enabled" not in target_columns:
        connection.execute("ALTER TABLE targets ADD COLUMN is_search_target_enabled INTEGER NOT NULL DEFAULT 1;")


def _needs_schema_reset(connection: Connection) -> bool:
    target_columns = _get_columns(connection, "targets")
    legacy_folder_columns = _get_columns(connection, "folders")
    file_columns = _get_columns(connection, "files")
    failed_file_columns = _get_columns(connection, "failed_files")

    if not target_columns and not legacy_folder_columns and not file_columns and not failed_file_columns:
        return False

    expected_target_columns = {
        "id",
        "full_path",
        "last_indexed_at",
        "exclude_keywords",
        "index_depth",
        "selected_extensions",
        "is_search_target_enabled",
        "indexed_file_count",
        "index_version",
        "created_at",
        "updated_at",
    }
    expected_file_columns = {
        "id",
        "full_path",
        "normalized_path",
        "file_name",
        "file_ext",
        "created_at",
        "mtime",
        "click_count",
        "size",
        "indexed_at",
        "last_error",
    }
    expected_index_run_columns = {
        "id",
        "is_running",
        "cancel_requested",
        "last_started_at",
        "last_finished_at",
        "last_error",
        "total_files",
        "error_count",
    }
    expected_failed_file_columns = {"id", "normalized_path", "file_name", "error_message", "last_failed_at"}
    expected_scheduler_settings_columns = {"id", "start_at", "is_enabled", "updated_at"}
    expected_scheduler_paths_columns = {"id", "scheduler_id", "folder_path", "sort_order"}
    expected_scheduler_runtime_columns = {
        "id",
        "status",
        "current_path",
        "process_id",
        "run_token",
        "last_started_at",
        "last_finished_at",
        "last_error",
    }
    expected_scheduler_logs_columns = {"id", "logged_at", "level", "message", "folder_path"}
    if legacy_folder_columns:
        return True
    index_run_columns = _get_columns(connection, "index_runs")
    scheduler_settings_columns = _get_columns(connection, "scheduler_settings")
    scheduler_paths_columns = _get_columns(connection, "scheduler_paths")
    scheduler_runtime_columns = _get_columns(connection, "scheduler_runtime")
    scheduler_logs_columns = _get_columns(connection, "scheduler_logs")
    legacy_file_columns = expected_file_columns - {"click_count"}
    return (
        target_columns != expected_target_columns
        or (file_columns != expected_file_columns and file_columns != legacy_file_columns)
        or index_run_columns != expected_index_run_columns
        or failed_file_columns != expected_failed_file_columns
        or (scheduler_settings_columns and scheduler_settings_columns != expected_scheduler_settings_columns)
        or (scheduler_paths_columns and scheduler_paths_columns != expected_scheduler_paths_columns)
        or (scheduler_runtime_columns and scheduler_runtime_columns != expected_scheduler_runtime_columns)
        or (scheduler_logs_columns and scheduler_logs_columns != expected_scheduler_logs_columns)
    )


def _drop_managed_schema_objects(connection: Connection) -> None:
    """
    アプリが管理する検索用テーブル・FTS・旧テーブルをまとめて削除する。
    旧 app_settings テーブルが残っていても、設定保存先は現在テキストファイルなので削除してよい。
    """
    connection.execute("DROP TABLE IF EXISTS app_settings;")
    connection.execute("DROP TABLE IF EXISTS file_segments_fts;")
    connection.execute("DROP TABLE IF EXISTS file_segments;")
    connection.execute("DROP TABLE IF EXISTS files;")
    connection.execute("DROP TABLE IF EXISTS failed_files;")
    connection.execute("DROP TABLE IF EXISTS scheduler_logs;")
    connection.execute("DROP TABLE IF EXISTS scheduler_paths;")
    connection.execute("DROP TABLE IF EXISTS scheduler_runtime;")
    connection.execute("DROP TABLE IF EXISTS scheduler_settings;")
    connection.execute("DROP TABLE IF EXISTS targets;")
    connection.execute("DROP TABLE IF EXISTS folders;")
    connection.execute("DROP TABLE IF EXISTS index_runs;")


def _get_columns(connection: Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row[1]) for row in rows}
