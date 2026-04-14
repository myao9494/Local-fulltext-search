from datetime import datetime

from pydantic import BaseModel


class DeleteIndexedFoldersRequest(BaseModel):
    """
    一括削除したいインデックス済みフォルダパスを受け取る。
    """

    folder_paths: list[str]


class IndexRunRequest(BaseModel):
    folder_id: int | None = None


class IndexStatusResponse(BaseModel):
    last_started_at: datetime | None
    last_finished_at: datetime | None
    total_files: int
    error_count: int
    is_running: bool
    cancel_requested: bool
    last_error: str | None


class FailedFileItem(BaseModel):
    normalized_path: str
    file_name: str
    error_message: str
    last_failed_at: datetime


class FailedFileListResponse(BaseModel):
    items: list[FailedFileItem]


class IndexedTargetItem(BaseModel):
    """
    インデックス済みフォルダ一覧の 1 行分情報。
    """

    full_path: str
    last_indexed_at: datetime | None
    indexed_file_count: int


class IndexedTargetListResponse(BaseModel):
    items: list[IndexedTargetItem]


class DeleteIndexedFoldersResponse(BaseModel):
    deleted_count: int
