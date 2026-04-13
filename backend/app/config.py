import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    """
    アプリ全体で共有する起動設定と保存先設定を保持する。
    """

    app_name: str = "Local Fulltext Search"
    bind_host: str = os.getenv("SEARCH_APP_HOST", "127.0.0.1")
    bind_port: int = int(os.getenv("SEARCH_APP_PORT", "8079"))
    data_dir: Path = Path(os.getenv("SEARCH_APP_DATA_DIR", "data"))
    database_name: str = os.getenv("SEARCH_APP_DB_NAME", "search.db")
    frontend_dist_dir: Path = Path(os.getenv("SEARCH_APP_FRONTEND_DIST_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

    @property
    def database_path(self) -> Path:
        return (self.data_dir / self.database_name).resolve()


settings = Settings()
