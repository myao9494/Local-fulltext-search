"""
アプリケーションのルーティングを検証する。
SPA 配信用の catch-all が API エンドポイントを覆わないことを担保する。
"""

from pathlib import Path
import sys

from starlette.routing import Match

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.main import create_app


def _cache_header_builder():
    app = create_app()
    return next(
        cell.cell_contents
        for route in app.routes
        for cell in (route.endpoint.__closure__ or [])
        if callable(cell.cell_contents) and getattr(cell.cell_contents, "__name__", "") == "build_static_cache_headers"
    )


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


def test_frontend_root_is_served_with_no_cache(tmp_path: Path, monkeypatch) -> None:
    """
    index.html は古いアプリシェルを保持しないよう no-cache で返す。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    header_source = _cache_header_builder()

    assert header_source(frontend_dist / "index.html")["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_service_worker_is_served_with_no_cache(tmp_path: Path, monkeypatch) -> None:
    """
    sw.js は更新検知できるよう no-cache で返す。
    """
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (frontend_dist / "sw.js").write_text("self.addEventListener('install', () => {})", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    header_source = _cache_header_builder()

    assert header_source(frontend_dist / "sw.js")["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_hashed_assets_are_served_as_immutable(tmp_path: Path, monkeypatch) -> None:
    """
    ハッシュ付き静的アセットは長期キャッシュ可能にする。
    """
    frontend_dist = tmp_path / "dist"
    assets_dir = frontend_dist / "assets"
    assets_dir.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (assets_dir / "index-abc123.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend_dist)

    header_source = _cache_header_builder()

    assert header_source(assets_dir / "index-abc123.js")["Cache-Control"] == "public, max-age=31536000, immutable"
