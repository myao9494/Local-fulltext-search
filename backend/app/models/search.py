from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.path_service import AbsolutePathRequiredError, normalize_path


def _validate_absolute_path_or_unc(value: str, *, field_name: str) -> str:
    """
    API で受け取る検索対象パスは、絶対パスまたは UNC パスだけを許可する。
    """
    if value == "":
        return value
    try:
        normalize_path(value)
    except AbsolutePathRequiredError as error:
        raise ValueError(f"{field_name} must be an absolute path or Windows UNC path.") from error
    return value


class SearchResultItem(BaseModel):
    file_id: int
    target_path: str
    file_name: str
    full_path: str
    file_ext: str
    created_at: datetime
    mtime: datetime
    click_count: int
    snippet: str


class SearchResponse(BaseModel):
    total: int
    items: list[SearchResultItem]
    used_existing_index: bool = False
    background_refresh_scheduled: bool = False


class SearchQueryParams(BaseModel):
    q: str = Field(min_length=1)
    full_path: str = ""
    search_all_enabled: bool = False
    skip_refresh: bool = False
    index_depth: int = Field(ge=0, le=128)
    refresh_window_minutes: int = Field(default=60, ge=0, le=1440)
    regex_enabled: bool = False
    index_types: str | None = None
    types: str | None = None
    exclude_keywords: str | None = None
    date_field: Literal["created", "modified"] = "created"
    sort_by: Literal["created", "modified", "click_count"] = "modified"
    sort_order: Literal["asc", "desc"] = "desc"
    created_from: date | None = None
    created_to: date | None = None
    limit: int = Field(default=20, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("full_path")
    @classmethod
    def validate_full_path_is_absolute(cls, value: str) -> str:
        """
        検索対象パスは、現在の作業ディレクトリに依存しない絶対パスだけを受け付ける。
        """
        return _validate_absolute_path_or_unc(value, field_name="full_path")

    @field_validator("created_to")
    @classmethod
    def validate_created_date_range(cls, value: date | None, info) -> date | None:
        """
        日付終了は開始日以上だけ受け付け、逆転した範囲を早期に弾く。
        """
        created_from = info.data.get("created_from")
        if value is not None and created_from is not None and value < created_from:
            raise ValueError("created_to must be on or after created_from.")
        return value


class SearchRequest(SearchQueryParams):
    pass


class IndexedSearchRequest(BaseModel):
    """
    既存インデックス専用検索の入力。
    既存 DB だけを対象にし、再インデックスは行わない。
    """

    q: str = Field(min_length=1)
    folder_path: str
    limit: int = Field(default=20, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("folder_path")
    @classmethod
    def validate_folder_path_is_absolute(cls, value: str) -> str:
        """
        対象フォルダは絶対パスまたは UNC パスだけを受け付ける。
        """
        return _validate_absolute_path_or_unc(value, field_name="folder_path")


class SearchClickRequest(BaseModel):
    file_id: int = Field(ge=1)


class SearchClickResponse(BaseModel):
    file_id: int
    click_count: int
