"""
インデックスAPI エンドポイント。リクエスト単位のDB接続を依存性注入で受け取る。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_index_service
from app.services.index_service import IndexService

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/status")
def get_status(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_status().model_dump()
