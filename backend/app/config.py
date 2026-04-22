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
    exclude_keywords_name: str = os.getenv("SEARCH_APP_EXCLUDE_KEYWORDS_NAME", "exclude_keywords.txt")
    hidden_indexed_targets_name: str = os.getenv(
        "SEARCH_APP_HIDDEN_INDEXED_TARGETS_NAME", "hidden_indexed_targets.txt"
    )
    synonym_groups_name: str = os.getenv("SEARCH_APP_SYNONYM_GROUPS_NAME", "synonym_groups.txt")
    search_target_folders_name: str = os.getenv("SEARCH_APP_SEARCH_TARGET_FOLDERS_NAME", "search_target_folders.txt")
    index_selected_extensions_name: str = os.getenv("SEARCH_APP_INDEX_SELECTED_EXTENSIONS_NAME", "index_selected_extensions.txt")
    custom_content_extensions_name: str = os.getenv("SEARCH_APP_CUSTOM_CONTENT_EXTENSIONS_NAME", "custom_content_extensions.txt")
    custom_filename_extensions_name: str = os.getenv(
        "SEARCH_APP_CUSTOM_FILENAME_EXTENSIONS_NAME", "custom_filename_extensions.txt"
    )
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

    @field_validator(
        "database_name",
        "exclude_keywords_name",
        "hidden_indexed_targets_name",
        "synonym_groups_name",
        "search_target_folders_name",
        "index_selected_extensions_name",
        "custom_content_extensions_name",
        "custom_filename_extensions_name",
    )
    @classmethod
    def _validate_file_name(cls, value: str) -> str:
        """
        database_name / exclude_keywords_name はファイル名のみを受け付け、パス区切りや親ディレクトリ指定を混入させない。
        """
        if "/" in value or "\\" in value or Path(value).name != value or value in {"", ".", ".."}:
            raise ValueError("configured file names must not include path separators.")
        return value

    @property
    def database_path(self) -> Path:
        return (self.data_dir / self.database_name).resolve()

    @property
    def exclude_keywords_path(self) -> Path:
        return (self.data_dir / self.exclude_keywords_name).resolve()

    @property
    def hidden_indexed_targets_path(self) -> Path:
        return (self.data_dir / self.hidden_indexed_targets_name).resolve()

    @property
    def synonym_groups_path(self) -> Path:
        return (self.data_dir / self.synonym_groups_name).resolve()

    @property
    def search_target_folders_path(self) -> Path:
        return (self.data_dir / self.search_target_folders_name).resolve()

    @property
    def index_selected_extensions_path(self) -> Path:
        return (self.data_dir / self.index_selected_extensions_name).resolve()

    @property
    def custom_content_extensions_path(self) -> Path:
        return (self.data_dir / self.custom_content_extensions_name).resolve()

    @property
    def custom_filename_extensions_path(self) -> Path:
        return (self.data_dir / self.custom_filename_extensions_name).resolve()


settings = Settings()
