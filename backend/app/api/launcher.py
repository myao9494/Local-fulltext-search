"""
ランチャーアプリのプロセス制御 API。
"""

from fastapi import APIRouter, Request

from app.services.launcher_service import LauncherManager

router = APIRouter(prefix="/api/launcher", tags=["launcher"])


def get_launcher_manager(request: Request) -> LauncherManager:
    """
    lifespan で初期化されたランチャーマネージャーを取得する。
    """
    return request.app.state.launcher_manager


@router.get("/status")
def get_launcher_status(request: Request) -> dict[str, object]:
    """
    ランチャーの起動状態とログ末尾を返す。
    """
    return get_launcher_manager(request).status()


@router.post("/start")
def start_launcher(request: Request) -> dict[str, object]:
    """
    ランチャーを起動する。
    """
    return get_launcher_manager(request).start()


@router.post("/stop")
def stop_launcher(request: Request) -> dict[str, object]:
    """
    ランチャーを停止する。
    """
    return get_launcher_manager(request).stop()


@router.post("/restart")
def restart_launcher(request: Request) -> dict[str, object]:
    """
    ランチャーを再起動する。
    """
    return get_launcher_manager(request).restart()
