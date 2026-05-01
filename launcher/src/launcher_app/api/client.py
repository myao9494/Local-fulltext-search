"""
ランチャーから既存 FastAPI バックエンドを呼び出す同期 API クライアント。
"""

from collections.abc import Callable
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen as default_urlopen

from launcher_app.models import SearchResponse, SearchResultItem

UrlOpen = Callable[..., Any]


class LauncherApiError(RuntimeError):
    """
    ランチャー UI に表示できるバックエンド通信エラー。
    """


class LauncherApiClient:
    """
    既存検索 API にランチャー向けの軽量な既定値を付けてアクセスする。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8079",
        *,
        timeout: float = 5.0,
        urlopen: UrlOpen = default_urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self._urlopen = urlopen

    def search(self, query: str, *, limit: int = 8) -> SearchResponse:
        """
        全 DB の既存インデックスを対象に、アクセス数順で検索する。
        """
        payload = {
            "q": query,
            "full_path": "",
            "search_all_enabled": True,
            "skip_refresh": True,
            "index_depth": 5,
            "refresh_window_minutes": 60,
            "search_target": "all",
            "sort_by": "click_count",
            "sort_order": "desc",
            "limit": limit,
            "offset": 0,
            "include_snippets": True,
        }
        response = self._request_json("/api/search", payload)
        return SearchResponse(
            total=int(response.get("total", 0)),
            has_more=bool(response.get("has_more", False)),
            items=[_parse_search_item(item) for item in response.get("items", [])],
        )

    def record_click(self, file_id: int) -> int:
        """
        選択された結果のアクセス数をバックエンドへ記録する。
        """
        response = self._request_json("/api/search/click", {"file_id": file_id})
        return int(response.get("click_count", 0))

    def open_location(self, path: str) -> None:
        """
        バックエンドの OS 連携 API でファイル位置を開く。
        """
        self._request_json("/api/files/open-location", {"path": path})

    def _request_json(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        """
        JSON POST を実行し、エラー時は detail を抽出して例外へ変換する。
        """
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._open(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise LauncherApiError(_read_error_message(error)) from error
        except URLError as error:
            raise LauncherApiError(str(error.reason)) from error
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LauncherApiError(str(error)) from error

    def _open(self, request: Request) -> Any:
        """
        標準 urlopen には timeout キーワードで渡し、テスト用スタブは従来の位置引数も許容する。
        """
        try:
            return self._urlopen(request, timeout=self.timeout)
        except TypeError as error:
            if "unexpected keyword argument" not in str(error):
                raise
            return self._urlopen(request, self.timeout)


def _parse_search_item(raw_item: object) -> SearchResultItem:
    """
    API の辞書レスポンスをランチャー内部モデルへ変換する。
    """
    item = raw_item if isinstance(raw_item, dict) else {}
    return SearchResultItem(
        file_id=int(item.get("file_id", 0)),
        result_kind=str(item.get("result_kind", "file")),
        target_path=str(item.get("target_path", "")),
        file_name=str(item.get("file_name", "")),
        full_path=str(item.get("full_path", "")),
        file_ext=str(item.get("file_ext", "")),
        created_at=str(item.get("created_at", "")),
        mtime=str(item.get("mtime", "")),
        click_count=int(item.get("click_count", 0)),
        snippet=str(item.get("snippet", "")),
    )


def _read_error_message(error: HTTPError) -> str:
    """
    FastAPI の detail 形式を優先してユーザー向け文言を取り出す。
    """
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return error.reason or f"HTTP {error.code}"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list) and detail:
        messages = [str(item.get("msg", "")) for item in detail if isinstance(item, dict)]
        return " ".join(message for message in messages if message) or f"HTTP {error.code}"
    return error.reason or f"HTTP {error.code}"
