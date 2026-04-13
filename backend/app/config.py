import os
from pathlib import Path

from pydantic import BaseModel, ValidationInfo, field_validator


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseModel):
    """
    アプリ全体で共有する起動設定と保存先設定を保持する。
    """

    app_name: str = "Local Fulltext Search"
    bind_host: str = os.getenv("SEARCH_APP_HOST", "127.0.0.1")
    bind_port: int = int(os.getenv("SEARCH_APP_PORT", "8079"))
    data_dir: Path = Path(os.getenv("SEARCH_APP_DATA_DIR", str(BACKEND_DIR / "data")))
    database_name: str = os.getenv("SEARCH_APP_DB_NAME", "search.db")
    frontend_dist_dir: Path = Path(os.getenv("SEARCH_APP_FRONTEND_DIST_DIR", str(PROJECT_ROOT_DIR / "frontend" / "dist")))

    @field_validator("data_dir", "frontend_dist_dir", mode="before")
    @classmethod
    def _normalize_config_paths(cls, value: str | Path, info: ValidationInfo) -> Path:
        """
        設定ファイル系のパスは内部では常に絶対パスへ正規化して保持する。
        相対指定は data_dir を backend 基準、frontend_dist_dir を project root 基準で解決する。
        """
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()

        base_dir = BACKEND_DIR if info.field_name == "data_dir" else PROJECT_ROOT_DIR
        return (base_dir / path).resolve()

    @field_validator("database_name")
    @classmethod
    def _validate_database_name(cls, value: str) -> str:
        """
        database_name はファイル名のみを受け付け、パス区切りや親ディレクトリ指定を混入させない。
        """
        if "/" in value or "\\" in value or Path(value).name != value or value in {"", ".", ".."}:
            raise ValueError("database_name must be a file name without path separators.")
        return value

    @property
    def database_path(self) -> Path:
        return (self.data_dir / self.database_name).resolve()


settings = Settings()
