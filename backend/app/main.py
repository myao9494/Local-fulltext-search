"""
アプリケーションエントリポイント。
起動時にDB接続を共有し、シャットダウン時にクローズする。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.folders import router as folders_router
from app.api.index import router as index_router
from app.api.search import router as search_router
from app.config import settings
from app.db.connection import get_connection
from app.db.schema import initialize_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時にDB接続を共有し、シャットダウン時にクローズする。"""
    connection = get_connection()
    initialize_schema(connection)
    app.state.db_connection = connection
    yield
    connection.close()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
