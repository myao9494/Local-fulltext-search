"""
アプリケーションエントリポイント。
起動時にDB接続を共有し、シャットダウン時にクローズする。
"""

from contextlib import asynccontextmanager
import logging
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import SimpleQueue

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.files import router as files_router
from app.api.folders import router as folders_router
from app.api.index import router as index_router
from app.api.search import router as search_router
from app.config import BACKEND_DIR, settings
from app.db.connection import get_connection
from app.db.schema import initialize_schema
from app.services.scheduler_service import SchedulerMonitor


def configure_logging() -> QueueListener:
    """
    INFO以上のログを標準出力とファイルへ非同期に流し、検索処理をディスクI/Oで待たせない。
    """
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(BACKEND_DIR / "backend.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    log_queue: SimpleQueue[logging.LogRecord] = SimpleQueue()
    queue_handler = QueueHandler(log_queue)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(queue_handler)

    listener = QueueListener(log_queue, stream_handler, file_handler, respect_handler_level=True)
    listener.start()
    return listener


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時にDB接続を共有し、シャットダウン時にクローズする。"""
    log_listener = configure_logging()
    connection = None
    scheduler_monitor = None
    try:
        connection = get_connection()
        initialize_schema(connection)
        scheduler_monitor = SchedulerMonitor()
        scheduler_monitor.start()
        app.state.db_connection = connection
        app.state.scheduler_monitor = scheduler_monitor
        app.state.log_listener = log_listener
        yield
    finally:
        if scheduler_monitor is not None:
            scheduler_monitor.stop()
        if connection is not None:
            connection.close()
        log_listener.stop()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(files_router)
    app.include_router(folders_router)
    app.include_router(index_router)
    app.include_router(search_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend_dist = settings.frontend_dist_dir
    index_file = frontend_dist / "index.html"

    if frontend_dist.exists() and index_file.exists():
        @app.get("/", include_in_schema=False)
        async def serve_frontend_root() -> FileResponse:
            return FileResponse(index_file)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")

            requested_path = (frontend_dist / full_path).resolve()
            try:
                requested_path.relative_to(frontend_dist.resolve())
            except ValueError as error:
                raise HTTPException(status_code=404, detail="Not found") from error

            if requested_path.is_file():
                return FileResponse(requested_path)

            return FileResponse(index_file)

    return app


app = create_app()
