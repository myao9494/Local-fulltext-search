"""
インデックスAPI エンドポイント。
実行状況と失敗ファイル一覧を提供し、UI から確認できるようにする。
必要に応じて DB を空の初期状態へ戻す。
"""

from fastapi import APIRouter, Depends
from fastapi import Query

from app.api.deps import get_index_service, get_scheduler_service
from app.models.indexing import (
    AppSettingsUpdateRequest,
    DeleteSearchTargetsRequest,
    DeleteIndexedFoldersRequest,
    ReindexSearchTargetsRequest,
    SchedulerUpdateRequest,
    SearchTargetAddRequest,
    SearchTargetUpdateRequest,
)
from app.services.index_service import IndexService
from app.services.scheduler_service import SchedulerService

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/status")
def get_status(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_status().model_dump()


@router.get("/settings")
def get_app_settings(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    端末ごとの localStorage ではなく、アプリ全体で共有する設定を返す。
    """
    return service.get_app_settings().model_dump()


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
        synonym_groups=payload.synonym_groups,
        index_selected_extensions=payload.index_selected_extensions,
        custom_content_extensions=payload.custom_content_extensions,
        custom_filename_extensions=payload.custom_filename_extensions,
    ).model_dump()


@router.get("/failed-files")
def get_failed_files(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_failed_files().model_dump()


@router.get("/targets")
def get_indexed_targets(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    """
    画面表示用に、インデックス済みフォルダ一覧を返す。
    """
    return service.list_indexed_targets().model_dump()


@router.delete("/targets")
def delete_indexed_targets(
    payload: DeleteIndexedFoldersRequest,
    service: IndexService = Depends(get_index_service),
) -> dict[str, object]:
    """
    選択したフォルダ群のインデックスをまとめて削除する。
    """
    return service.delete_indexed_folders(payload.folder_paths).model_dump()


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
    return service.add_search_target(folder_path=payload.folder_path).model_dump()


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
