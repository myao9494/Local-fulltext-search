from fastapi import APIRouter, Depends, Query

from app.models.search import SearchQueryParams, SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/api", tags=["search"])


def get_search_service() -> SearchService:
    return SearchService()


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    full_path: str = Query(..., min_length=1),
    index_depth: int = Query(..., ge=0, le=128),
    refresh_window_minutes: int = Query(default=60, ge=0, le=1440),
    types: str | None = None,
    exclude_keywords: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    params = SearchQueryParams(
        q=q,
        full_path=full_path,
        index_depth=index_depth,
        refresh_window_minutes=refresh_window_minutes,
        types=types,
        exclude_keywords=exclude_keywords,
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
