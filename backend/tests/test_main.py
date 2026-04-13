"""
アプリケーションのルーティングを検証する。
SPA 配信用の catch-all が API エンドポイントを覆わないことを担保する。
"""

from pathlib import Path

from starlette.routing import Match

from app.config import settings
from app.main import create_app


def test_health_route_takes_precedence_over_spa_catch_all(tmp_path: Path, monkeypatch) -> None:
    """
    frontend/dist が存在しても /api/health は catch-all より先に解決される。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    app = create_app()
    scope = {"type": "http", "path": "/api/health", "method": "GET"}

    first_full_match = next(
        route
        for route in app.router.routes
        if route.matches(scope)[0] == Match.FULL
    )

    assert first_full_match.path == "/api/health"
