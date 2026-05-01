"""
ランチャー用 API クライアントが既存 FastAPI サーバーへ最小検索条件を送ることを検証する。
"""

import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from launcher_app.api.client import LauncherApiClient, LauncherApiError


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


def test_search_posts_launcher_defaults() -> None:
    """
    ランチャー検索は全 DB の既存インデックスを優先し、軽い検索条件で POST する。
    """
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
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

    client = LauncherApiClient(base_url="http://127.0.0.1:8000", urlopen=fake_urlopen)

    response = client.search("alpha")

    assert captured["url"] == "http://127.0.0.1:8000/api/search"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 5.0
    assert captured["body"] == {
        "q": "alpha",
        "full_path": "",
        "search_all_enabled": True,
        "skip_refresh": True,
        "index_depth": 5,
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


def test_api_error_extracts_detail() -> None:
    """
    API エラーは FastAPI の detail をユーザー向けメッセージとして保持する。
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

    with pytest.raises(LauncherApiError, match="backend is unavailable"):
        client.search("alpha")


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
