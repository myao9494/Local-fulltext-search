"""
APIの依存性注入。リクエスト単位のDB接続を提供する。
"""

from collections.abc import Generator
from sqlite3 import Connection

from fastapi import Depends

from app.db.connection import get_connection
from app.services.index_service import IndexService
from app.services.search_service import SearchService


def get_db_connection() -> Generator[Connection, None, None]:
    """リクエストごとに新しい DB 接続を生成し、処理後に閉じる。"""
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
