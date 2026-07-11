"""8001 Open/UIハブの契約とプロセス管理を検証する。"""

from pathlib import Path
from io import BytesIO
import subprocess

from fastapi.testclient import TestClient

from app import open_hub
from app.config import settings
from app.services.open_hub_service import OpenHubManager


class FakeProcess:
    pid = 24680

    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_fullpath_opens_existing_absolute_path(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "document.txt"
    target.write_text("content", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(open_hub, "open_local_path", lambda path: opened.append(path))

    response = TestClient(open_hub.create_open_hub_app()).get("/api/fullpath", params={"path": str(target)})

    assert response.status_code == 200
    assert opened == [str(target)]


def test_fullpath_rejects_cross_site_request(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "document.txt"
    target.touch()
    monkeypatch.setattr(open_hub, "open_local_path", lambda path: None)

    response = TestClient(open_hub.create_open_hub_app()).get(
        "/api/fullpath",
        params={"path": str(target)},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_fullpath_rejects_relative_path_as_client_error(monkeypatch) -> None:
    """OS openへ渡せない相対パスは、サーバー障害ではなく入力エラーとして返す。"""
    monkeypatch.setattr(open_hub, "open_local_path", lambda path: None)

    response = TestClient(open_hub.create_open_hub_app(), raise_server_exceptions=False).get(
        "/api/fullpath",
        params={"path": "relative/document.txt"},
    )

    assert response.status_code == 422


def test_api_proxy_preserves_backend_error_response(monkeypatch) -> None:
    """8001配下のAPIは8079のステータス・本文・Content-Typeを保つ。"""
    class FakeHttpError(open_hub.HTTPError):
        def __init__(self) -> None:
            super().__init__("http://127.0.0.1:8079/api/search", 409, "Conflict", {"Content-Type": "application/json"}, BytesIO(b'{"detail":"conflict"}'))

    class FakeOpener:
        def open(self, request, timeout):
            raise FakeHttpError()

    monkeypatch.setattr(open_hub, "_proxyless_opener", FakeOpener())

    response = TestClient(open_hub.create_open_hub_app()).get("/api/search?q=test")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "conflict"}


def test_folder_url_serves_spa_index(tmp_path: Path, monkeypatch) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend)

    response = TestClient(open_hub.create_open_hub_app()).get("/", params={"path": str(tmp_path)})

    assert response.status_code == 200
    assert "id='root'" in response.text


def test_open_hub_manager_starts_separate_process(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    manager = OpenHubManager()
    manager.log_path = tmp_path / "open_hub.log"
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = manager.start()

    assert result["is_running"] is True
    assert captured["command"][-2:] == ["-m", "app.open_hub"]
    assert captured["kwargs"]["env"]["SEARCH_APP_OPEN_HUB_PORT"] == "8001"


def test_open_hub_spawn_failure_does_not_abort_backend_startup(tmp_path: Path, monkeypatch) -> None:
    """8001子プロセスを起動できなくても8079の起動処理は継続できる。"""
    manager = OpenHubManager()
    manager.log_path = tmp_path / "open_hub.log"
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")))

    result = manager.start()

    assert result["is_running"] is False
    assert "blocked" in str(result["last_error"])
    assert "blocked" in manager.log_path.read_text(encoding="utf-8")
