from datetime import datetime

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    file_id: int
    target_id: int
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
    types: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchRequest(SearchQueryParams):
    pass
