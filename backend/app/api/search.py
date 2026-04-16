"""
検索API エンドポイント。リクエスト単位のDB接続を依存性注入で受け取る。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_search_service
from app.models.search import SearchClickRequest, SearchClickResponse, SearchQueryParams, SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    full_path: str = Query(default=""),
    search_all_enabled: bool = Query(default=False),
    index_depth: int = Query(..., ge=0, le=128),
    refresh_window_minutes: int = Query(default=60, ge=0, le=1440),
    regex_enabled: bool = Query(default=False),
    index_types: str | None = None,
    types: str | None = None,
    exclude_keywords: str | None = None,
    date_field: str = Query(default="created"),
    sort_by: str = Query(default="modified"),
    sort_order: str = Query(default="desc"),
    created_from: date | None = None,
    created_to: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    params = SearchQueryParams(
        q=q,
        full_path=full_path,
        search_all_enabled=search_all_enabled,
        index_depth=index_depth,
        refresh_window_minutes=refresh_window_minutes,
        regex_enabled=regex_enabled,
        index_types=index_types,
        types=types,
        exclude_keywords=exclude_keywords,
        date_field=date_field,
        sort_by=sort_by,
        sort_order=sort_order,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return service.search(params)


@router.post("/search", response_model=SearchResponse)
def search_with_body(
    params: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    return service.search(params)


@router.post("/search/click", response_model=SearchClickResponse)
def record_search_click(
    payload: SearchClickRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchClickResponse:
    return SearchClickResponse(file_id=payload.file_id, click_count=service.record_click(payload.file_id))
