"""
APIの依存性注入。リクエストごとにDB接続を開閉する。
SQLite 接続をスレッド間で共有せず、並列リクエスト時のトランザクション干渉を避ける。
"""

from collections.abc import Iterator
from sqlite3 import Connection

from fastapi import Depends

from app.db.connection import get_connection
from app.services.index_service import IndexService
from app.services.scheduler_service import SchedulerService
from app.services.search_service import SearchService


def get_db_connection() -> Iterator[Connection]:
    """リクエストスコープの SQLite 接続を返し、処理後に閉じる。"""
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def get_search_service(connection: Connection = Depends(get_db_connection)) -> SearchService:
    """リクエスト単位の接続を使用する SearchService を返す。"""
    return SearchService(connection=connection)


def get_index_service(connection: Connection = Depends(get_db_connection)) -> IndexService:
    """リクエスト単位の接続を使用する IndexService を返す。"""
    return IndexService(connection=connection)


def get_scheduler_service(connection: Connection = Depends(get_db_connection)) -> SchedulerService:
    """リクエスト単位の接続を使用する SchedulerService を返す。"""
    return SchedulerService(connection=connection)
