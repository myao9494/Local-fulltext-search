"""
ランチャー用 API クライアントが既存 FastAPI サーバーへ最小検索条件を送ることを検証するテスト。
index_depth が省略され、バックエンド側で無制限（99999）になるように変更されたため、リクエストペイロードから index_depth が送信されないことを検証する。
"""
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from launcher_app.api import client as client_module
from launcher_app.api.client import LauncherApiClient, LauncherApiError, default_urlopen


class StubResponse:
    """
    urllib のレスポンスとして扱える最小スタブ。
    """

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "StubResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _stub_search_response() -> StubResponse:
    """
    検索 API テスト共通のスタブレスポンスを返す。
    """
    return StubResponse(
        {
            "total": 1,
            "items": [
                {
                    "file_id": 9,
                    "result_kind": "file",
                    "target_path": "/tmp/docs/a.md",
                    "file_name": "a.md",
                    "full_path": "/tmp/docs/a.md",
                    "file_ext": ".md",
                    "created_at": "2026-01-01T00:00:00",
                    "mtime": "2026-01-02T00:00:00",
                    "click_count": 3,
                    "snippet": "<mark>alpha</mark>",
                }
            ],
        }
    )


def test_search_posts_mac_defaults(monkeypatch) -> None:
    """
    macOS ではインデックス更新を許可する /api/search エンドポイントを使用する。
    """
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return _stub_search_response()

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    response = client.search("alpha")

    assert captured["url"] == "http://127.0.0.1:8000/api/search"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 5.0
    assert captured["body"] == {
        "q": "alpha",
        "full_path": "",
        "search_all_enabled": False,
        "skip_refresh": False,
        "refresh_window_minutes": 60,
        "search_target": "all",
        "sort_by": "click_count",
        "sort_order": "desc",
        "limit": 8,
        "offset": 0,
        "include_snippets": True,
    }
    assert response.total == 1
    assert response.items[0].file_name == "a.md"


def test_search_posts_windows_defaults(monkeypatch) -> None:
    """
    Windows（非 Mac）では既存インデックスのみの /api/search/indexed を使用する。
    """
    monkeypatch.setattr("platform.system", lambda: "Windows")
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return _stub_search_response()

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    response = client.search("alpha")

    assert captured["url"] == "http://127.0.0.1:8000/api/search/indexed"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 5.0
    assert captured["body"] == {
        "q": "alpha",
        "folder_path": "",
        "limit": 8,
        "offset": 0,
    }
    assert response.total == 1
    assert response.items[0].file_name == "a.md"


def test_search_posts_gantt_include_for_all_platforms(monkeypatch) -> None:
    """
    gantt 選択時は Windows でも通常検索に gantt 追加フラグを指定する。
    """
    monkeypatch.setattr("platform.system", lambda: "Windows")
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return _stub_search_response()

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    client.search("alpha", include_gantt_tasks=True)

    assert captured["url"] == "http://127.0.0.1:8000/api/search"
    assert captured["body"] == {
        "q": "alpha",
        "full_path": "",
        "search_all_enabled": True,
        "skip_refresh": True,
        "source_type": "local",
        "refresh_window_minutes": 0,
        "search_target": "all",
        "sort_by": "click_count",
        "sort_order": "desc",
        "limit": 8,
        "offset": 0,
        "include_snippets": True,
        "include_gantt_tasks": True,
    }


def test_default_base_url_uses_project_backend_port() -> None:
    """
    ランチャーの既定接続先は本プロジェクトのバックエンド既定ポート 8079 を使う。
    """
    client = LauncherApiClient(urlopen=lambda request, timeout: StubResponse({"total": 0, "items": []}))

    assert client.base_url == "http://127.0.0.1:8079/"


def test_record_click_posts_file_id() -> None:
    """
    結果オープン時のアクセス数更新は file_id だけを POST する。
    """
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return StubResponse({"file_id": 4, "click_count": 12})

    client = LauncherApiClient(base_url="http://127.0.0.1:8000/", urlopen=fake_urlopen)

    assert client.record_click(4) == 12
    assert captured["url"] == "http://127.0.0.1:8000/api/search/click"
    assert captured["body"] == {"file_id": 4}


def test_create_gantt_task_posts_to_gantt_api() -> None:
    """
    メモ入力から作った payload は gantt API の /tasks へそのまま POST する。
    """
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return StubResponse({"id": 99, "text": "AI テストタスク"})

    client = LauncherApiClient(
        base_url="http://127.0.0.1:8079",
        gantt_api_base_url="http://localhost:8000/api",
        urlopen=fake_urlopen,
    )

    response = client.create_gantt_task({"text": "AI テストタスク", "parent": 0})

    assert response == {"id": 99, "text": "AI テストタスク"}
    assert captured["url"] == "http://localhost:8000/api/tasks"
    assert captured["method"] == "POST"
    assert captured["body"] == {"text": "AI テストタスク", "parent": 0}


def test_get_app_settings_reads_shared_web_settings() -> None:
    """
    ランチャーは Web 設定ドロワーで保存した共有設定を GET で取得する。
    """
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return StubResponse({"gantt_parent": 12})

    client = LauncherApiClient(base_url="http://127.0.0.1:8079", urlopen=fake_urlopen)

    assert client.get_app_settings() == {"gantt_parent": 12}
    assert captured["url"] == "http://127.0.0.1:8079/api/index/settings"
    assert captured["method"] == "GET"


def test_api_error_extracts_detail() -> None:
    """
    API エラーは HTTP ステータスと FastAPI の detail をユーザー向けメッセージとして保持する。
    """
    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        raise HTTPError(
            request.full_url,
            500,
            "Server Error",
            {},
            StubErrorBody({"detail": "backend is unavailable"}),
        )

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    with pytest.raises(LauncherApiError, match="HTTP 500 Server Error: backend is unavailable"):
        client.search("alpha")


def test_api_error_includes_plain_forbidden_body() -> None:
    """
    社内プロキシ等が返す素の Forbidden も HTTP ステータス付きで表示する。
    """
    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            StubPlainErrorBody("Forbidden"),
        )

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    with pytest.raises(LauncherApiError, match="HTTP 403 Forbidden: Forbidden"):
        client.search("alpha")


def test_default_urlopen_uses_proxyless_opener(monkeypatch) -> None:
    """
    ランチャーの既定 HTTP 実行は環境変数プロキシではなくプロキシ無効の opener を使う。
    """
    calls: dict[str, object] = {}

    class StubOpener:
        def open(self, request: Request, timeout: float) -> StubResponse:
            calls["url"] = request.full_url
            calls["timeout"] = timeout
            return StubResponse({"total": 0, "items": []})

    monkeypatch.setattr(client_module, "_proxyless_opener", StubOpener())
    request = Request("http://127.0.0.1:8079/api/search/indexed", data=b"{}", method="POST")

    response = default_urlopen(request, timeout=1.5)

    assert calls == {"url": "http://127.0.0.1:8079/api/search/indexed", "timeout": 1.5}
    assert isinstance(response, StubResponse)


class StubErrorBody:
    """
    HTTPError.fp として JSON 本文を返すスタブ。
    """

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        """
        HTTPError の一時ファイルクローザーから呼ばれる close を受ける。
        """
        return None


class StubPlainErrorBody:
    """
    HTTPError.fp としてプレーンテキスト本文を返すスタブ。
    """

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload.encode("utf-8")

    def close(self) -> None:
        return None
