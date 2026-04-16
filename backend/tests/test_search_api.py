"""
検索 API のルート関数が並び替え条件とクリック記録を受け渡せることを検証する。
"""

from app.api.search import record_search_click, search_with_body
from app.models.search import SearchClickRequest, SearchRequest


class StubSearchService:
    """
    検索 API ルート関数の入出力を確かめるための最小スタブ。
    """

    def __init__(self) -> None:
        self.last_search_params = None
        self.last_clicked_file_id = None

    def search(self, params: SearchRequest) -> object:
        self.last_search_params = params

        class Response:
            def model_dump(self) -> dict[str, object]:
                return {"total": 0, "items": []}

        return Response()

    def record_click(self, file_id: int) -> int:
        self.last_clicked_file_id = file_id
        return 7


def test_search_with_body_passes_sort_options_to_service() -> None:
    """
    POST /api/search は並び替え指定をそのまま SearchRequest でサービスへ渡す。
    """
    service = StubSearchService()

    payload = search_with_body(
        SearchRequest(
            q="alpha",
            full_path="",
            index_depth=5,
            sort_by="click_count",
            sort_order="desc",
        ),
        service,
    )

    assert payload.model_dump()["total"] == 0
    assert service.last_search_params is not None
    assert service.last_search_params.sort_by == "click_count"
    assert service.last_search_params.sort_order == "desc"


def test_search_with_body_passes_search_all_flag_to_service() -> None:
    """
    POST /api/search は全 DB 検索フラグをそのまま SearchRequest でサービスへ渡す。
    """
    service = StubSearchService()

    search_with_body(
        SearchRequest(
            q="alpha",
            full_path="/tmp/docs",
            search_all_enabled=True,
            index_depth=5,
        ),
        service,
    )

    assert service.last_search_params is not None
    assert service.last_search_params.search_all_enabled is True
    assert service.last_search_params.full_path == "/tmp/docs"


def test_record_search_click_returns_updated_count() -> None:
    """
    POST /api/search/click は更新後のアクセス数を返す。
    """
    service = StubSearchService()

    payload = record_search_click(SearchClickRequest(file_id=3), service)

    assert payload.file_id == 3
    assert payload.click_count == 7
    assert service.last_clicked_file_id == 3
