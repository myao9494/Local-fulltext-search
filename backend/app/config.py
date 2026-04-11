import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Local Fulltext Search"
    bind_host: str = os.getenv("SEARCH_APP_HOST", "127.0.0.1")
    bind_port: int = int(os.getenv("SEARCH_APP_PORT", "8000"))
    data_dir: Path = Path(os.getenv("SEARCH_APP_DATA_DIR", "data"))
    database_name: str = os.getenv("SEARCH_APP_DB_NAME", "search.db")

    @property
    def database_path(self) -> Path:
        return (self.data_dir / self.database_name).resolve()


settings = Settings()
