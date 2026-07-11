"""Open/UIハブの管理状態API。"""

from fastapi import APIRouter, Request

from app.services.open_hub_service import OpenHubManager

router = APIRouter(prefix="/api/open-hub", tags=["open-hub"])


def get_manager(request: Request) -> OpenHubManager:
    return request.app.state.open_hub_manager


@router.get("/status")
def get_status(request: Request) -> dict[str, object]:
    return get_manager(request).status()


@router.post("/start")
def start(request: Request) -> dict[str, object]:
    return get_manager(request).start()


@router.post("/stop")
def stop(request: Request) -> dict[str, object]:
    return get_manager(request).stop()
