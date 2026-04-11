import sqlite3
from pathlib import Path

from app.config import settings


def ensure_data_dir() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)


def normalize_db_path(path: Path) -> Path:
    return path.expanduser().resolve()


def get_connection() -> sqlite3.Connection:
    ensure_data_dir()
    db_path = normalize_db_path(settings.database_path)
    connection = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    return connection
