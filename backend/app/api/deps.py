"""
APIの依存性注入。アプリケーション共有のDB接続を提供する。
リクエストごとの再接続を回避し、PRAGMAの再設定オーバーヘッドを削減する。
"""

from sqlite3 import Connection

from fastapi import Depends, Request

from app.services.index_service import IndexService
from app.services.scheduler_service import SchedulerService
from app.services.search_service import SearchService


def get_db_connection(request: Request) -> Connection:
    """app.state.db_connection に保持された共有接続を返す。"""
    return request.app.state.db_connection


def get_search_service(connection: Connection = Depends(get_db_connection)) -> SearchService:
    """リクエスト単位の接続を使用する SearchService を返す。"""
    return SearchService(connection=connection)


def get_index_service(connection: Connection = Depends(get_db_connection)) -> IndexService:
    """リクエスト単位の接続を使用する IndexService を返す。"""
    return IndexService(connection=connection)


def get_scheduler_service(connection: Connection = Depends(get_db_connection)) -> SchedulerService:
    """リクエスト単位の接続を使用する SchedulerService を返す。"""
    return SchedulerService(connection=connection)
