"""
8001番でWeb UIと「検索結果を開く」契約を提供する独立Openハブ。
"""

from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, build_opener, ProxyHandler

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.config import settings
from app.models.files import OpenFileLocationRequest

API_BASE_URL = os.getenv("SEARCH_APP_OPEN_HUB_API_BASE_URL", f"http://127.0.0.1:{settings.bind_port}").rstrip("/")
_proxyless_opener = build_opener(ProxyHandler({}))
_HOP_BY_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}


def open_local_path(path: str) -> None:
    """ローカルファイルまたはフォルダをOS既定アプリで開く。"""
    system_name = platform.system()
    if system_name == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = ["/usr/bin/open", path] if system_name == "Darwin" else ["xdg-open", path]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def proxy_to_api(request: UrlRequest) -> Response:
    """8079への同期HTTP通信を実行し、上流の応答をFastAPI応答へ変換する。"""
    try:
        with _proxyless_opener.open(request, timeout=30) as upstream:
            response_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}
            return Response(upstream.read(), status_code=upstream.status, headers=response_headers)
    except HTTPError as error:
        response_headers = {key: value for key, value in error.headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}
        return Response(error.read(), status_code=error.code, headers=response_headers)
    except URLError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"API backend is unavailable: {error.reason}") from error


def create_open_hub_app() -> FastAPI:
    app = FastAPI(title="Local Fulltext Search Open Hub")

    @app.get("/_open_hub/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "api_base_url": API_BASE_URL}

    @app.get("/api/fullpath", response_class=HTMLResponse)
    def open_full_path(request: Request, path: str = Query(min_length=1)) -> HTMLResponse:
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site open requests are not allowed.")
        try:
            validated = OpenFileLocationRequest(path=path)
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error.errors(include_context=False),
            ) from error
        try:
            path_exists = Path(validated.path).exists()
        except OSError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid path: {error}") from error
        if not path_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path does not exist.")
        try:
            open_local_path(validated.path)
        except OSError as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to open path: {error}") from error
        return HTMLResponse("<!doctype html><meta charset='utf-8'><title>Opened</title><p>対象を開きました。このタブは閉じて構いません。</p>")

    @app.api_route("/api/{api_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_api(api_path: str, request: Request) -> Response:
        query = f"?{request.url.query}" if request.url.query else ""
        url = f"{API_BASE_URL}/api/{api_path}{query}"
        body = await request.body()
        headers = {key: value for key, value in request.headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "host"}
        proxy_request = UrlRequest(url, data=body or None, headers=headers, method=request.method)
        return await run_in_threadpool(proxy_to_api, proxy_request)

    frontend_dist = settings.frontend_dist_dir.resolve()
    index_file = frontend_dist / "index.html"
    if index_file.is_file():
        @app.get("/", include_in_schema=False)
        def serve_root() -> FileResponse:
            return FileResponse(index_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

        @app.get("/{full_path:path}", include_in_schema=False)
        def serve_spa(full_path: str) -> FileResponse:
            requested = (frontend_dist / full_path).resolve()
            try:
                requested.relative_to(frontend_dist)
            except ValueError as error:
                raise HTTPException(status_code=404, detail="Not found") from error
            return FileResponse(requested if requested.is_file() else index_file)
    return app


app = create_open_hub_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.open_hub_host, port=settings.open_hub_port, reload=False)
