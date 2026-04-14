"""
インデックスAPI エンドポイント。
実行状況と失敗ファイル一覧を提供し、UI から確認できるようにする。
必要に応じて DB を空の初期状態へ戻す。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_index_service
from app.models.indexing import DeleteIndexedFoldersRequest
from app.services.index_service import IndexService

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/status")
def get_status(service: IndexService = Depends(get_index_service)) -> dict[str, object]:
    return service.get_status().model_dump()


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
