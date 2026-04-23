from datetime import datetime

from pydantic import BaseModel

DEFAULT_EXCLUDE_KEYWORDS = "\n".join(
    [
        "node_modules",
        ".git",
        "old",
        "旧",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "coverage",
        ".next",
        ".turbo",
        ".parcel-cache",
    ]
)


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


class SearchTargetItem(BaseModel):
    """
    検索対象フォルダ一覧の 1 行分情報。
    """

    full_path: str
    is_enabled: bool
    last_indexed_at: datetime | None
    indexed_file_count: int


class SearchTargetListResponse(BaseModel):
    items: list[SearchTargetItem]


class SearchTargetCoverageResponse(BaseModel):
    """
    指定パスが有効な検索対象フォルダ配下に含まれるかを返す。
    """

    normalized_path: str
    is_covered: bool
    covering_path: str | None


class SearchTargetUpdateRequest(BaseModel):
    """
    検索対象フォルダの有効/無効を切り替える。
    """

    folder_path: str
    is_enabled: bool


class SearchTargetAddRequest(BaseModel):
    """
    検索対象フォルダへ新規追加する。
    """

    folder_path: str


class ReindexSearchTargetsRequest(BaseModel):
    """
    指定した検索対象フォルダ群を再インデックスする。
    """

    folder_paths: list[str]


class ReindexSearchTargetsResponse(BaseModel):
    reindexed_count: int


class DeleteSearchTargetsRequest(BaseModel):
    """
    検索対象フォルダ一覧から削除するパス群を受け取る。
    """

    folder_paths: list[str]


class DeleteSearchTargetsResponse(BaseModel):
    deleted_count: int


class DeleteIndexedFoldersResponse(BaseModel):
    deleted_count: int


class AppSettingsResponse(BaseModel):
    """
    アプリ全体で共有する設定値を返す。
    """

    exclude_keywords: str
    hidden_indexed_targets: str
    synonym_groups: str
    obsidian_sidebar_explorer_data_path: str
    index_selected_extensions: str
    custom_content_extensions: str
    custom_filename_extensions: str


class AppSettingsUpdateRequest(BaseModel):
    """
    利用者が保存したいアプリ設定値を受け取る。
    """

    exclude_keywords: str | None = None
    hidden_indexed_targets: str | None = None
    synonym_groups: str | None = None
    obsidian_sidebar_explorer_data_path: str | None = None
    index_selected_extensions: str | None = None
    custom_content_extensions: str | None = None
    custom_filename_extensions: str | None = None


class SchedulerLogItem(BaseModel):
    """
    スケジューラー実行中に記録したログ 1 行分。
    """

    logged_at: datetime
    level: str
    message: str
    folder_path: str | None = None


class SchedulerSettingsResponse(BaseModel):
    """
    スケジューラー設定・実行状況・最新ログをまとめて返す。
    """

    paths: list[str]
    start_at: datetime | None
    is_enabled: bool
    status: str
    last_started_at: datetime | None
    last_finished_at: datetime | None
    current_path: str | None
    last_error: str | None
    logs: list[SchedulerLogItem]


class SchedulerUpdateRequest(BaseModel):
    """
    スケジューラー開始時に使う対象パス群と開始日時。
    """

    paths: list[str]
    start_at: datetime
