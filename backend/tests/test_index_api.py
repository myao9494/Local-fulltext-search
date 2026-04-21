"""
インデックス API の初期化系とアプリ設定系エンドポイントを検証する。
DB 初期化ボタンと設定保存が安全に機能することを担保する。
"""

from pathlib import Path

from starlette.routing import Match

from app.api.index import (
    add_search_target,
    cancel_indexing,
    delete_search_targets,
    delete_indexed_targets,
    get_app_settings,
    get_indexed_targets,
    get_search_targets,
    get_scheduler_settings,
    reset_database,
    set_search_target_enabled,
    start_scheduler,
    update_app_settings,
)
from app.config import settings
from app.main import create_app
from app.models.indexing import (
    AppSettingsUpdateRequest,
    DeleteIndexedFoldersRequest,
    SchedulerUpdateRequest,
    DeleteSearchTargetsRequest,
    SearchTargetAddRequest,
    SearchTargetUpdateRequest,
)


class StubIndexService:
    """
    ルート関数テスト用の簡易 IndexService スタブ。
    """

    def __init__(self) -> None:
        self.did_reset = False
        self.did_cancel = False
        self.deleted_target_ids: list[int] = []
        self.saved_exclude_keywords = ".git\nnode_modules"
        self.saved_synonym_groups = "スマートフォン,スマホ,モバイル"
        self.saved_index_selected_extensions = ".md\n.json"
        self.saved_custom_content_extensions = ".py\n.dat"
        self.saved_custom_filename_extensions = ".CAE"
        self.search_targets = [
            {
                "full_path": "/tmp/docs",
                "is_enabled": True,
                "last_indexed_at": "2026-04-15T00:00:00+00:00",
                "indexed_file_count": 4,
            }
        ]
        self.scheduler_payload = {
            "paths": ["/tmp/docs", "/tmp/share"],
            "start_at": "2026-04-20T00:00:00+00:00",
            "is_enabled": True,
            "status": "scheduled",
            "last_started_at": None,
            "last_finished_at": None,
            "current_path": None,
            "last_error": None,
            "logs": [],
        }

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

    def get_app_settings(self) -> object:
        class AppSettings:
            def __init__(
                self,
                exclude_keywords: str,
                synonym_groups: str,
                index_selected_extensions: str,
                custom_content_extensions: str,
                custom_filename_extensions: str,
            ) -> None:
                self.exclude_keywords = exclude_keywords
                self.synonym_groups = synonym_groups
                self.index_selected_extensions = index_selected_extensions
                self.custom_content_extensions = custom_content_extensions
                self.custom_filename_extensions = custom_filename_extensions

            def model_dump(self) -> dict[str, object]:
                return {
                    "exclude_keywords": self.exclude_keywords,
                    "synonym_groups": self.synonym_groups,
                    "index_selected_extensions": self.index_selected_extensions,
                    "custom_content_extensions": self.custom_content_extensions,
                    "custom_filename_extensions": self.custom_filename_extensions,
                }

        return AppSettings(
            self.saved_exclude_keywords,
            self.saved_synonym_groups,
            self.saved_index_selected_extensions,
            self.saved_custom_content_extensions,
            self.saved_custom_filename_extensions,
        )

    def update_app_settings(
        self,
        *,
        exclude_keywords: str | None = None,
        synonym_groups: str | None = None,
        index_selected_extensions: str | None = None,
        custom_content_extensions: str | None = None,
        custom_filename_extensions: str | None = None,
    ) -> object:
        if exclude_keywords is not None:
            self.saved_exclude_keywords = exclude_keywords
        if synonym_groups is not None:
            self.saved_synonym_groups = synonym_groups
        if index_selected_extensions is not None:
            self.saved_index_selected_extensions = index_selected_extensions
        if custom_content_extensions is not None:
            self.saved_custom_content_extensions = custom_content_extensions
        if custom_filename_extensions is not None:
            self.saved_custom_filename_extensions = custom_filename_extensions
        return self.get_app_settings()

    def get_scheduler_settings(self) -> object:
        class SchedulerSettings:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def model_dump(self) -> dict[str, object]:
                return self.payload

        return SchedulerSettings(self.scheduler_payload)

    def schedule_indexing(self, *, paths: list[str], start_at) -> object:
        self.scheduler_payload = {
            **self.scheduler_payload,
            "paths": paths,
            "start_at": start_at.isoformat(),
            "is_enabled": True,
            "status": "scheduled",
            "logs": [],
        }
        return self.get_scheduler_settings()

    def list_search_targets(self) -> object:
        class SearchTargets:
            def __init__(self, items: list[dict[str, object]]) -> None:
                self.items = items

            def model_dump(self) -> dict[str, object]:
                return {"items": self.items}

        return SearchTargets(self.search_targets)

    def set_search_target_enabled(self, *, folder_path: str, is_enabled: bool) -> object:
        for item in self.search_targets:
            if item["full_path"] == folder_path:
                item["is_enabled"] = is_enabled
                return self.list_search_targets()
        self.search_targets.append(
            {
                "full_path": folder_path,
                "is_enabled": is_enabled,
                "last_indexed_at": None,
                "indexed_file_count": 0,
            }
        )
        return self.list_search_targets()

    def add_search_target(self, *, folder_path: str) -> object:
        return self.set_search_target_enabled(folder_path=folder_path, is_enabled=True)

    def delete_search_targets(self, folder_paths: list[str]) -> object:
        removed = 0
        for folder_path in folder_paths:
            current_count = len(self.search_targets)
            self.search_targets = [item for item in self.search_targets if item["full_path"] != folder_path]
            if len(self.search_targets) < current_count:
                removed += 1

        class DeleteResult:
            def __init__(self, deleted_count: int) -> None:
                self.deleted_count = deleted_count

            def model_dump(self) -> dict[str, object]:
                return {"deleted_count": self.deleted_count}

        return DeleteResult(removed)


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


def test_get_search_targets_endpoint_returns_folder_list() -> None:
    """
    ルート関数は検索対象フォルダ一覧をそのまま返す。
    """
    service = StubIndexService()

    payload = get_search_targets(service)

    assert payload["items"][0]["full_path"] == "/tmp/docs"
    assert payload["items"][0]["is_enabled"] is True


def test_set_search_target_enabled_endpoint_updates_flag() -> None:
    """
    ルート関数は指定フォルダの有効/無効を更新した一覧を返す。
    """
    service = StubIndexService()

    payload = set_search_target_enabled(
        SearchTargetUpdateRequest(folder_path="/tmp/docs", is_enabled=False),
        service,
    )

    assert payload["items"][0]["full_path"] == "/tmp/docs"
    assert payload["items"][0]["is_enabled"] is False


def test_add_search_target_endpoint_adds_target() -> None:
    """
    ルート関数は検索対象フォルダを有効状態で追加した一覧を返す。
    """
    service = StubIndexService()

    payload = add_search_target(SearchTargetAddRequest(folder_path="/tmp/new"), service)

    assert any(item["full_path"] == "/tmp/new" and item["is_enabled"] is True for item in payload["items"])


def test_delete_search_targets_endpoint_removes_targets() -> None:
    """
    ルート関数は検索対象フォルダの削除件数を返す。
    """
    service = StubIndexService()

    payload = delete_search_targets(DeleteSearchTargetsRequest(folder_paths=["/tmp/docs"]), service)

    assert payload["deleted_count"] == 1


def test_delete_indexed_targets_endpoint_returns_deleted_count() -> None:
    """
    ルート関数は選択した folder_path 一覧をサービスへ渡し、削除件数を返す。
    """
    service = StubIndexService()

    payload = delete_indexed_targets(DeleteIndexedFoldersRequest(folder_paths=["/tmp/a", "/tmp/b"]), service)

    assert payload["deleted_count"] == 2


def test_get_app_settings_endpoint_returns_saved_settings() -> None:
    """
    ルート関数は保存済みのアプリ設定をそのまま返す。
    """
    service = StubIndexService()

    payload = get_app_settings(service)

    assert payload["exclude_keywords"] == ".git\nnode_modules"
    assert payload["synonym_groups"] == "スマートフォン,スマホ,モバイル"
    assert payload["index_selected_extensions"] == ".md\n.json"
    assert payload["custom_content_extensions"] == ".py\n.dat"
    assert payload["custom_filename_extensions"] == ".CAE"


def test_update_app_settings_endpoint_returns_updated_settings() -> None:
    """
    ルート関数は除外キーワード更新をサービスへ渡し、保存後の値を返す。
    """
    service = StubIndexService()

    payload = update_app_settings(
        AppSettingsUpdateRequest(
            exclude_keywords="dist\nbuild",
            synonym_groups="スマートフォン,スマホ,モバイル\nノートPC,ラップトップ",
            index_selected_extensions=".md\n.py",
            custom_content_extensions=".py\n.dat",
            custom_filename_extensions=".cae",
        ),
        service,
    )

    assert payload["exclude_keywords"] == "dist\nbuild"
    assert service.saved_exclude_keywords == "dist\nbuild"
    assert payload["synonym_groups"] == "スマートフォン,スマホ,モバイル\nノートPC,ラップトップ"
    assert service.saved_synonym_groups == "スマートフォン,スマホ,モバイル\nノートPC,ラップトップ"
    assert payload["index_selected_extensions"] == ".md\n.py"
    assert payload["custom_content_extensions"] == ".py\n.dat"
    assert payload["custom_filename_extensions"] == ".cae"


def test_get_scheduler_settings_endpoint_returns_saved_schedule() -> None:
    """
    ルート関数は保存済みのスケジューラー設定をそのまま返す。
    """
    service = StubIndexService()

    payload = get_scheduler_settings(service)

    assert payload["paths"] == ["/tmp/docs", "/tmp/share"]
    assert payload["status"] == "scheduled"
    assert payload["is_enabled"] is True


def test_start_scheduler_endpoint_returns_scheduled_settings() -> None:
    """
    ルート関数はスケジュール開始要求をサービスへ渡し、保存後の値を返す。
    """
    service = StubIndexService()

    payload = start_scheduler(
        SchedulerUpdateRequest(
            paths=["/tmp/docs", "/tmp/share"],
            start_at="2026-04-21T09:30:00+09:00",
        ),
        service,
    )

    assert payload["paths"] == ["/tmp/docs", "/tmp/share"]
    assert payload["start_at"] == "2026-04-21T09:30:00+09:00"
    assert payload["status"] == "scheduled"


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


def test_search_targets_routes_are_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータに検索対象フォルダ一覧・更新・追加 API が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    get_scope = {"type": "http", "path": "/api/index/search-targets", "method": "GET"}
    put_scope = {"type": "http", "path": "/api/index/search-targets", "method": "PUT"}
    post_scope = {"type": "http", "path": "/api/index/search-targets", "method": "POST"}
    delete_scope = {"type": "http", "path": "/api/index/search-targets", "method": "DELETE"}

    first_get_match = next(route for route in app.router.routes if route.matches(get_scope)[0] == Match.FULL)
    first_put_match = next(route for route in app.router.routes if route.matches(put_scope)[0] == Match.FULL)
    first_post_match = next(route for route in app.router.routes if route.matches(post_scope)[0] == Match.FULL)
    first_delete_match = next(route for route in app.router.routes if route.matches(delete_scope)[0] == Match.FULL)

    assert first_get_match.path == "/api/index/search-targets"
    assert first_put_match.path == "/api/index/search-targets"
    assert first_post_match.path == "/api/index/search-targets"
    assert first_delete_match.path == "/api/index/search-targets"


def test_search_target_coverage_route_is_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータに検索対象カバー判定 API が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    scope = {"type": "http", "path": "/api/index/search-targets/coverage", "method": "GET"}

    first_match = next(route for route in app.router.routes if route.matches(scope)[0] == Match.FULL)

    assert first_match.path == "/api/index/search-targets/coverage"


def test_app_settings_routes_are_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータにアプリ設定の取得・更新 API が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    get_scope = {"type": "http", "path": "/api/index/settings", "method": "GET"}
    put_scope = {"type": "http", "path": "/api/index/settings", "method": "PUT"}

    first_get_match = next(route for route in app.router.routes if route.matches(get_scope)[0] == Match.FULL)
    first_put_match = next(route for route in app.router.routes if route.matches(put_scope)[0] == Match.FULL)

    assert first_get_match.path == "/api/index/settings"
    assert first_put_match.path == "/api/index/settings"


def test_scheduler_routes_are_registered(tmp_path: Path, monkeypatch) -> None:
    """
    create_app 後のルータにスケジューラー取得・開始 API が登録される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    get_scope = {"type": "http", "path": "/api/index/scheduler", "method": "GET"}
    post_scope = {"type": "http", "path": "/api/index/scheduler/start", "method": "POST"}

    first_get_match = next(route for route in app.router.routes if route.matches(get_scope)[0] == Match.FULL)
    first_post_match = next(route for route in app.router.routes if route.matches(post_scope)[0] == Match.FULL)

    assert first_get_match.path == "/api/index/scheduler"
    assert first_post_match.path == "/api/index/scheduler/start"
