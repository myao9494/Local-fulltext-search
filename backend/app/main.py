from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.folders import router as folders_router
from app.api.index import router as index_router
from app.api.search import router as search_router
from app.config import settings
from app.db.connection import get_connection
from app.db.schema import initialize_schema


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    connection = get_connection()
    initialize_schema(connection)
    connection.close()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(folders_router)
    app.include_router(index_router)
    app.include_router(search_router)
    return app


app = create_app()
