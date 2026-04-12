import sqlite3
from pathlib import Path

from app.config import settings


def ensure_data_dir() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)


def normalize_db_path(path: Path) -> Path:
    return path.expanduser().resolve()


def get_connection() -> sqlite3.Connection:
    """
    SQLite接続を作成し、パフォーマンス最適化PRAGMAを設定する。
    - WAL: 読み書き並行性向上
    - synchronous=NORMAL: WAL併用時に安全かつ高速
    - cache_size: 64MBに拡大してI/O削減
    - temp_store=MEMORY: 一時テーブルをメモリ上に配置
    - mmap_size: 256MBのメモリマップ読み取り
    """
    ensure_data_dir()
    db_path = normalize_db_path(settings.database_path)
    connection = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    connection.execute("PRAGMA cache_size = -64000;")
    connection.execute("PRAGMA temp_store = MEMORY;")
    connection.execute("PRAGMA mmap_size = 268435456;")
    return connection
