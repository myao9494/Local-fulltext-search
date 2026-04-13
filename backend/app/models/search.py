from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.services.path_service import AbsolutePathRequiredError, normalize_path


class SearchResultItem(BaseModel):
    file_id: int
    target_path: str
    file_name: str
    full_path: str
    file_ext: str
    mtime: datetime
    snippet: str


class SearchResponse(BaseModel):
    total: int
    items: list[SearchResultItem]


class SearchQueryParams(BaseModel):
    q: str = Field(min_length=1)
    full_path: str = Field(min_length=1)
    index_depth: int = Field(ge=0, le=128)
    refresh_window_minutes: int = Field(default=60, ge=0, le=1440)
    regex_enabled: bool = False
    types: str | None = None
    exclude_keywords: str | None = None
    limit: int = Field(default=20, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("full_path")
    @classmethod
    def validate_full_path_is_absolute(cls, value: str) -> str:
        """
        検索対象パスは、現在の作業ディレクトリに依存しない絶対パスだけを受け付ける。
        """
        try:
            normalize_path(value)
        except AbsolutePathRequiredError as error:
            raise ValueError("full_path must be an absolute path or Windows UNC path.") from error
        return value


class SearchRequest(SearchQueryParams):
    pass
