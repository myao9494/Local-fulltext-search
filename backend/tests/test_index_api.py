"""
インデックス API の初期化系エンドポイントを検証する。
DB 初期化ボタンから安全に空スキーマへ戻せることを担保する。
"""

from pathlib import Path

from starlette.routing import Match

from app.api.index import reset_database
from app.config import settings
from app.main import create_app


class StubIndexService:
    """
    ルート関数テスト用の簡易 IndexService スタブ。
    """

    def __init__(self) -> None:
        self.did_reset = False

    def reset_database(self) -> None:
        self.did_reset = True

    def get_status(self) -> object:
        class Status:
            def model_dump(self) -> dict[str, object]:
                return {
                    "last_started_at": None,
                    "last_finished_at": None,
                    "total_files": 0,
                    "error_count": 0,
                    "is_running": False,
                    "last_error": None,
                }

        return Status()


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
