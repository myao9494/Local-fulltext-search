"""
インデックスAPI エンドポイント。
実行状況と失敗ファイル一覧を提供し、UI から確認できるようにする。
file_manager 連携用に、本文検索を行わない Everything 互換のファイル/フォルダ検索も提供する。
必要に応じて DB を空の初期状態へ戻す。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi import Query

from app.api.deps import get_index_service, get_scheduler_service, get_search_service
from app.models.indexing import (
    AppSettingsUpdateRequest,
    DeleteIndexedTargetsRequest,
    DeleteSearchTargetsRequest,
    ReindexSearchTargetsRequest,
    SchedulerUpdateRequest,
    SearchTargetAddRequest,
    SearchTargetUpdateRequest,
    SynonymListResponse,
)
from app.models.search import SearchQueryParams
from app.services.index_service import IndexService
from app.services.scheduler_service import SchedulerService
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/index", tags=["index"])


def _map_everything_sort(sort: str) -> tuple[Literal["created", "modified", "click_count"], Literal["asc", "desc"]]:
    """
    Everything 互換の sort 指定を、本アプリの検索サービスが扱える並び順へ変換する。
    """
    if sort == "date_modified":
        return "modified", "desc"
    return "click_count", "desc"


def _to_unix_timestamp(value) -> float:
    """
    datetime を file_index_service 互換の Unix timestamp 秒へ変換する。
    """
    return float(value.timestamp())


@router.get("")
def search_everything_compatible(
    search: str = Query(..., description="検索クエリ"),
    count: int = Query(default=100, ge=1, le=1000, description="取得件数"),
    offset: int = Query(default=0, ge=0, description="オフセット"),
    sort: str = Query(default="name", description="ソート順"),
    ascending: int = Query(default=1, description="昇順(1)/降順(0)"),
    path: str | None = Query(default=None, description="検索対象フォルダ"),
    file_type: str = Query(default="all", description="ファイルタイプ（all/file/directory）"),
    service: SearchService = Depends(get_search_service),
) -> dict[str, object]:
    """
    file_index_service 互換でファイル名・フォルダ名だけを検索する。
    本文検索や検索時の自動再インデックスは行わない。
    """
    sort_by, default_sort_order = _map_everything_sort(sort)
    sort_order: Literal["asc", "desc"] = "asc" if ascending == 1 and sort == "date_modified" else default_sort_order
    type_filter = None if file_type == "all" else file_type
    response = service.search(
        SearchQueryParams(
            q=search,
            full_path=path or "",
            search_all_enabled=not bool(path),
            skip_refresh=True,
            source_type="local",
            index_depth=0,
            search_target="filename_and_folder",
            types=type_filter,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=count,
            offset=offset,
            include_snippets=False,
        )
    )

    return {
        "totalResults": response.total,
        "results": [
            {
                "name": item.file_name,
                "path": item.full_path,
                "type": "directory" if item.result_kind == "folder" else "file",
                "size": 0,
                "date_modified": _to_unix_timestamp(item.mtime),
            }
            for item in response.items
        ],
    }


@router.get("/status")
def get_status(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    payload = service.get_status().model_dump()
    row = service.connection.execute("SELECT COUNT(*) FROM files WHERE source_type = 'local'").fetchone()
    total_indexed = int(row[0]) if row is not None else 0
    payload["ready"] = not payload["is_running"]
    payload["total_indexed"] = total_indexed
    payload["version"] = "local-fulltext-search"
    payload["paths"] = []
    return payload


@router.get("/settings")
def get_app_settings(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    端末ごとの localStorage ではなく、アプリ全体で共有する設定を返す。
    """
    return service.get_app_settings().model_dump()


@router.get("/synonyms", response_model=SynonymListResponse)
def get_synonyms(service: IndexService = Depends(get_index_service)) -> SynonymListResponse:
    """
    構造化された同義語リストを返す。
    """
    return service.get_synonyms()


@router.put("/settings")
def update_app_settings(
    payload: AppSettingsUpdateRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    アプリ全体で共有する設定を保存し、保存後の値を返す。
    """
    return service.update_app_settings(
        exclude_keywords=payload.exclude_keywords,
        web_exclude_keywords=payload.web_exclude_keywords,
        hidden_indexed_targets=payload.hidden_indexed_targets,
        synonym_groups=payload.synonym_groups,
        obsidian_sidebar_explorer_data_path=payload.obsidian_sidebar_explorer_data_path,
        index_selected_extensions=payload.index_selected_extensions,
        custom_content_extensions=payload.custom_content_extensions,
        custom_filename_extensions=payload.custom_filename_extensions,
    ).model_dump()


@router.get("/failed-files")
def get_failed_files(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_failed_files().model_dump()


@router.get("/targets")
def get_indexed_targets(
    service: IndexService = Depends(get_index_service),
    source_type: str = Query("local"),
) -> dict[str, object]:
    """
    画面表示用に、インデックス済みフォルダ一覧を返す。
    """
    return service.list_indexed_targets(source_type=source_type).model_dump()


@router.delete("/targets")
def delete_indexed_targets(
    payload: DeleteIndexedTargetsRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    選択したフォルダ群のインデックスをまとめて削除する。
    """
    target_paths = getattr(payload, "target_paths", None)
    folder_paths = getattr(payload, "folder_paths", None)
    paths = target_paths if target_paths is not None else folder_paths or []
    return service.delete_indexed_targets(paths).model_dump()


@router.get("/search-targets")
def get_search_targets(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    検索対象フォルダ一覧（有効/無効フラグ付き）を返す。
    """
    return service.list_search_targets().model_dump()


@router.get("/search-targets/coverage")
def get_search_target_coverage(
    folder_path: str = Query(...),
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    指定パスが有効な検索対象フォルダ配下かどうかを返す。
    """
    return service.get_search_target_coverage(folder_path=folder_path).model_dump()


@router.put("/search-targets")
def set_search_target_enabled(
    payload: SearchTargetUpdateRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    検索対象フォルダの有効/無効を更新する。
    """
    return service.set_search_target_enabled(folder_path=payload.folder_path, is_enabled=payload.is_enabled).model_dump()


@router.post("/search-targets")
def add_search_target(
    payload: SearchTargetAddRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    検索対象フォルダへ新規追加する。
    """
    return service.add_search_target(folder_path=payload.folder_path, index_depth=payload.index_depth).model_dump()


@router.delete("/search-targets")
def delete_search_targets(
    payload: DeleteSearchTargetsRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    検索対象フォルダ一覧から指定パスを削除する。
    """
    return service.delete_search_targets(payload.folder_paths).model_dump()


@router.post("/search-targets/reindex")
def reindex_search_targets(
    payload: ReindexSearchTargetsRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    指定した検索対象フォルダ群を順次再インデックスする。
    """
    return service.reindex_search_targets(payload.folder_paths).model_dump()


@router.post("/cancel")
def cancel_indexing(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    実行中インデックスへ中止要求を送り、現在のステータスを返す。
    """
    service.cancel_indexing()
    return {
        "message": "Cancellation requested.",
        "status": service.get_status().model_dump(),
    }


@router.post("/reset")
def reset_database(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    インデックス DB を初期化し、空スキーマだけを再作成する。
    """
    service.reset_database()
    return {
        "message": "Database was reset.",
        "status": service.get_status().model_dump(),
    }


@router.get("/scheduler")
def get_scheduler_settings(service: SchedulerService = Depends(get_scheduler_service)) -> dict[str, object]:
    """
    スケジューラー設定・実行状況・ログをまとめて返す。
    """
    return service.get_scheduler_settings().model_dump()


@router.post("/scheduler/start")
def start_scheduler(
    payload: SchedulerUpdateRequest,
    service: SchedulerService = Depends(get_scheduler_service),
) -> dict[str, object]:
    """
    スケジュール対象パスと開始日時を保存し、開始待ち状態へ切り替える。
    """
    return service.schedule_indexing(paths=payload.paths, start_at=payload.start_at).model_dump()
