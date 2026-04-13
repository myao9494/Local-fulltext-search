"""
インデックスAPI エンドポイント。
実行状況と失敗ファイル一覧を提供し、UI から確認できるようにする。
必要に応じて DB を空の初期状態へ戻す。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_index_service
from app.services.index_service import IndexService

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/status")
def get_status(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_status().model_dump()


@router.get("/failed-files")
def get_failed_files(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_failed_files().model_dump()


@router.post("/reset")
def reset_database(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    インデックス DB を初期化し、空スキーマだけを再作成する。
    """
    service.reset_database()
    return {
        "message": "Database was reset.",
        "status": service.get_status().model_dump(),
    }
