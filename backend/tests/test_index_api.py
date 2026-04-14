"""
インデックス API の初期化系エンドポイントを検証する。
DB 初期化ボタンから安全に空スキーマへ戻せることを担保する。
"""

from pathlib import Path

from starlette.routing import Match

from app.api.index import cancel_indexing, delete_indexed_targets, get_indexed_targets, reset_database
from app.config import settings
from app.main import create_app
from app.models.indexing import DeleteIndexedFoldersRequest


class StubIndexService:
    """
    ルート関数テスト用の簡易 IndexService スタブ。
    """

    def __init__(self) -> None:
        self.did_reset = False
        self.did_cancel = False
        self.deleted_target_ids: list[int] = []

    def reset_database(self) -> None:
        self.did_reset = True

    def cancel_indexing(self) -> None:
        self.did_cancel = True

    def get_status(self) -> object:
        class Status:
            def model_dump(self) -> dict[str, object]:
                return {
                    "last_started_at": None,
                    "last_finished_at": None,
                    "total_files": 0,
                    "error_count": 0,
                    "is_running": False,
                    "cancel_requested": False,
                    "last_error": None,
                }

        return Status()

    def list_indexed_targets(self) -> object:
        class IndexedTargets:
            def model_dump(self) -> dict[str, object]:
                return {
                    "items": [
                        {
                            "full_path": "/tmp/docs",
                            "last_indexed_at": "2026-04-15T00:00:00+00:00",
                            "indexed_file_count": 4,
                        }
                    ]
                }

        return IndexedTargets()

    def delete_indexed_folders(self, folder_paths: list[str]) -> object:
        self.deleted_target_ids = list(range(len(folder_paths)))

        class DeleteResult:
            def model_dump(self) -> dict[str, object]:
                return {"deleted_count": len(folder_paths)}

        return DeleteResult()


def test_reset_database_endpoint_returns_status_payload() -> None:
    """
    ルート関数は reset_database を呼び、初期化後のステータスを返す。
    """
    service = StubIndexService()

    payload = reset_database(service)

    assert service.did_reset is True
    assert payload["message"] == "Database was reset."
    assert payload["status"]["total_files"] == 0
    assert payload["status"]["error_count"] == 0
    assert payload["status"]["is_running"] is False
    assert payload["status"]["cancel_requested"] is False


def test_cancel_indexing_endpoint_returns_status_payload() -> None:
    """
    ルート関数は cancel_indexing を呼び、現在のステータスを返す。
    """
    service = StubIndexService()

    payload = cancel_indexing(service)

    assert service.did_cancel is True
    assert payload["message"] == "Cancellation requested."
    assert payload["status"]["is_running"] is False
    assert payload["status"]["cancel_requested"] is False


def test_get_indexed_targets_endpoint_returns_folder_list() -> None:
    """
    ルート関数はインデックス済みフォルダ一覧をそのまま返す。
    """
    service = StubIndexService()

    payload = get_indexed_targets(service)

    assert payload["items"][0]["full_path"] == "/tmp/docs"
    assert payload["items"][0]["indexed_file_count"] == 4


def test_delete_indexed_targets_endpoint_returns_deleted_count() -> None:
    """
    ルート関数は選択した folder_path 一覧をサービスへ渡し、削除件数を返す。
    """
    service = StubIndexService()

    payload = delete_indexed_targets(DeleteIndexedFoldersRequest(folder_paths=["/tmp/a", "/tmp/b"]), service)

    assert payload["deleted_count"] == 2


def test_reset_database_route_is_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータに POST /api/index/reset が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    scope = {"type": "http", "path": "/api/index/reset", "method": "POST"}

    first_full_match = next(
        route
        for route in app.router.routes
        if route.matches(scope)[0] == Match.FULL
    )

    assert first_full_match.path == "/api/index/reset"


def test_cancel_indexing_route_is_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータに POST /api/index/cancel が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    scope = {"type": "http", "path": "/api/index/cancel", "method": "POST"}

    first_full_match = next(
        route
        for route in app.router.routes
        if route.matches(scope)[0] == Match.FULL
    )

    assert first_full_match.path == "/api/index/cancel"


def test_indexed_targets_routes_are_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータにインデックス済みフォルダ一覧・削除 API が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    get_scope = {"type": "http", "path": "/api/index/targets", "method": "GET"}
    delete_scope = {"type": "http", "path": "/api/index/targets", "method": "DELETE"}

    first_get_match = next(route for route in app.router.routes if route.matches(get_scope)[0] == Match.FULL)
    first_delete_match = next(route for route in app.router.routes if route.matches(delete_scope)[0] == Match.FULL)

    assert first_get_match.path == "/api/index/targets"
    assert first_delete_match.path == "/api/index/targets"
