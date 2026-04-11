from fastapi import APIRouter

from app.services.index_service import IndexService

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/status")
def get_status() -> dict[str, object]:
    return IndexService().get_status().model_dump()
