from datetime import UTC, date, datetime, time, timedelta
from html import escape
import json
import logging
import math
from pathlib import Path
import re
from sqlite3 import Connection
import threading
import time as time_module
import unicodedata
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.config import settings
from app.db.connection import get_connection
from app.db.schema import initialize_schema
from app.extractors.text_extractor import normalize_extension_filter
from app.models.search import IndexedSearchRequest, SearchQueryParams, SearchResponse, SearchResultItem
from app.services.cjk_bigram import build_cjk_bigram_match_query
from app.services.index_service import IndexService
from app.services.path_service import get_descendant_path_prefix, get_descendant_path_range, normalize_path, normalize_path_str

_BACKGROUND_REFRESH_LOCK = threading.Lock()
_BACKGROUND_REFRESH_KEYS: set[tuple[str, str, int, str]] = set()
_BACKGROUND_REFRESH_LAST_SCHEDULED_AT: dict[tuple[str, str, int, str], float] = {}
_OBSIDIAN_SYNC_LOCK = threading.Lock()
_OBSIDIAN_SYNC_RUNNING = False
BACKGROUND_REFRESH_RETRY_COOLDOWN_SECONDS = 30.0
OBSIDIAN_RANK_SCORE_SCALE = 1000.0
GANTT_LINK_FIELD_NAMES = frozenset({"hyperlink", "link", "url", "href", "input_url", "external_url"})

logger = logging.getLogger(__name__)


class SearchService:
    """
    全文検索とファイル名検索をまとめて提供する。
    ユーザー入力は FTS5 構文としてではなく、通常の検索語として安全に扱う。
    """

    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()
        self.index_service = IndexService(connection=self.connection)

    def _normalize_web_url(self, value: str) -> str:
        """
        Web 検索の絞り込みに使う URL をフラグメントなしへ正規化する。
        """
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Web target must be an http or https URL.")
        path = parsed.path or "/"
        return urlunparse(
            parsed._replace(
                scheme=parsed.scheme.lower(),
                netloc=parsed.netloc.lower(),
                path=path,
                params="",
                fragment="",
            )
        )

    def search(self, params: SearchQueryParams) -> SearchResponse:
        if params.source_type == "gantt":
            return self._search_gantt_tasks(params)

        if params.include_gantt_tasks:
            return self._search_with_gantt_tasks(params)

        normalized_target_path = ""
        if params.full_path:
            normalized_target_path = (
                self._normalize_web_url(params.full_path)
                if params.source_type == "web"
                else normalize_path_str(params.full_path)
            )
        app_settings = self.index_service.get_app_settings()
        default_exclude_keywords = (
            app_settings.web_exclude_keywords if params.source_type == "web" else app_settings.exclude_keywords
        )
        effective_exclude_keywords = (
            params.exclude_keywords if params.exclude_keywords is not None else default_exclude_keywords
        )
        excluded_keywords = self.index_service._parse_exclude_keywords(effective_exclude_keywords)
        refresh_flags = {"used_existing_index": False, "background_refresh_scheduled": False}

        index_depth = params.index_depth if params.index_depth is not None else 99999

        if not normalized_target_path and not params.search_all_enabled:
            self._refresh_search_targets_for_search_without_path(
                refresh_window_minutes=params.refresh_window_minutes,
                effective_exclude_keywords=effective_exclude_keywords,
                index_depth=index_depth,
                index_types=params.index_types,
                custom_content_extensions=app_settings.custom_content_extensions,
                custom_filename_extensions=app_settings.custom_filename_extensions,
                source_type=params.source_type,
            )
        if normalized_target_path and not params.search_all_enabled and not params.skip_refresh:
            refresh_flags = self._refresh_target_for_search(
                normalized_target_path=normalized_target_path,
                refresh_window_minutes=params.refresh_window_minutes,
                effective_exclude_keywords=effective_exclude_keywords,
                index_depth=index_depth,
                index_types=params.index_types,
                custom_content_extensions=app_settings.custom_content_extensions,
                custom_filename_extensions=app_settings.custom_filename_extensions,
            )

        start_time = time_module.perf_counter()
        response = self._execute_search(
            params=params,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
            app_settings=app_settings,
            path_depth_limit=index_depth,
        )
        elapsed = time_module.perf_counter() - start_time
        logger.info("Search total time: %.3fs (q=%s, search_all=%s)", elapsed, params.q, params.search_all_enabled)

        self._schedule_obsidian_access_sync()
        return response.model_copy(update=refresh_flags)

    def _search_with_gantt_tasks(self, params: SearchQueryParams) -> SearchResponse:
        """
        通常検索の結果に gantt タスク検索結果を追加し、同じ並び替え・ページングで返す。
        """
        base_params = params.model_copy(update={"include_gantt_tasks": False, "limit": 1000, "offset": 0})
        base_response = self.search(base_params)
        gantt_response = self._search_gantt_tasks(params.model_copy(update={"limit": 1000, "offset": 0}))
        merged_items = self._sort_search_result_items(
            [*base_response.items, *gantt_response.items],
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        page_items = merged_items[params.offset : params.offset + params.limit]
        has_more = params.offset + len(page_items) < len(merged_items)
        return SearchResponse(
            total=len(merged_items),
            items=page_items,
            has_more=has_more,
            next_offset=params.offset + len(page_items) if has_more else None,
            used_existing_index=base_response.used_existing_index,
            background_refresh_scheduled=base_response.background_refresh_scheduled,
        )

    def _search_gantt_tasks(self, params: SearchQueryParams) -> SearchResponse:
        """
        gantt アプリの `/tasks` JSON をオンデマンドで取得し、タスク本文を検索結果として返す。
        """
        tasks = self._fetch_gantt_tasks()
        include_terms, exclude_terms = self._split_search_terms(params.q.strip())
        lowered_include_terms = [term.lower() for term in include_terms]
        lowered_exclude_terms = [term.lower() for term in exclude_terms]
        matched_items: list[SearchResultItem] = []
        now = datetime.now(tz=UTC)
        for index, task in enumerate(tasks, start=1):
            task_text = self._stringify_gantt_task(task)
            haystack = task_text.lower()
            if lowered_include_terms and not all(term in haystack for term in lowered_include_terms):
                continue
            if lowered_exclude_terms and any(term in haystack for term in lowered_exclude_terms):
                continue
            task_id = self._extract_gantt_task_id(task, fallback=index)
            task_name = self._extract_gantt_task_name(task, fallback=f"Task {task_id}")
            task_link = self._extract_gantt_task_link(task)
            matched_items.append(
                SearchResultItem(
                    file_id=-task_id,
                    result_kind="file",
                    source_type="gantt",
                    target_path=settings.gantt_api_base_url.rstrip("/") + "/tasks",
                    file_name=task_name,
                    full_path=f"gantt://tasks/{task_id}",
                    file_ext=".gantt",
                    created_at=now,
                    mtime=now,
                    click_count=0,
                    snippet=self._build_gantt_snippet(task_text, include_terms) if params.include_snippets else "",
                    gantt_link=task_link,
                )
            )

        page_items = matched_items[params.offset : params.offset + params.limit]
        has_more = params.offset + len(page_items) < len(matched_items)
        return SearchResponse(
            total=len(matched_items),
            items=page_items,
            has_more=has_more,
            next_offset=params.offset + len(page_items) if has_more else None,
        )

    def _fetch_gantt_tasks(self) -> list[object]:
        """
        gantt API のタスク一覧レスポンスからタスク配列を取り出す。
        """
        url = settings.gantt_api_base_url.rstrip("/") + "/tasks"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"gantt API からタスクを取得できません: {error}") from error
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("tasks", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _stringify_gantt_task(self, task: object) -> str:
        """
        gantt タスクの任意 JSON を検索しやすい平文へ変換する。
        hyperlink などのリンク項目は検索・除外語判定に使わない。
        """
        if isinstance(task, dict):
            parts: list[str] = []
            for key, value in task.items():
                if key.lower() in GANTT_LINK_FIELD_NAMES:
                    continue
                if isinstance(value, (dict, list)):
                    parts.append(self._stringify_gantt_task(value))
                elif value is not None:
                    parts.append(f"{key}: {value}")
            return " ".join(parts)
        if isinstance(task, list):
            return " ".join(self._stringify_gantt_task(item) for item in task)
        return str(task)

    def _extract_gantt_task_id(self, task: object, *, fallback: int) -> int:
        """
        gantt タスクの代表 ID を整数へ寄せ、なければ表示順を使う。
        """
        if isinstance(task, dict):
            for key in ("id", "task_id", "uid"):
                value = task.get(key)
                try:
                    return max(1, int(str(value)))
                except (TypeError, ValueError):
                    continue
        return fallback

    def _extract_gantt_task_name(self, task: object, *, fallback: str) -> str:
        """
        gantt タスクのタイトル候補を検索結果名として返す。
        """
        if isinstance(task, dict):
            for key in ("text", "title", "name", "label", "content"):
                value = task.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return fallback

    def _extract_gantt_task_link(self, task: object) -> str | None:
        """
        gantt タスクに設定された外部リンク候補を取り出す。
        """
        if not isinstance(task, dict):
            return None
        for key in ("hyperlink", "link", "url", "href", "input_url", "external_url"):
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def open_gantt_task_input(self, task_id: int) -> None:
        """
        gantt アプリの入力画面を、開いているガント画面上で表示する。
        """
        url = f"{settings.gantt_api_base_url.rstrip('/')}/tasks/{task_id}/open-input"
        request = Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=3.0):
                return
        except OSError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"gantt タスクを開けません: {error}") from error

    def _build_gantt_snippet(self, task_text: str, terms: list[str]) -> str:
        """
        gantt タスク本文の先頭付近を、検索語を mark で強調した短いスニペットにする。
        """
        snippet = escape(task_text[:280])
        for term in terms:
            if not term:
                continue
            snippet = re.sub(re.escape(escape(term)), lambda match: f"<mark>{match.group(0)}</mark>", snippet, flags=re.IGNORECASE)
        return snippet

    def _refresh_search_targets_for_search_without_path(
        self,
        *,
        refresh_window_minutes: int,
        effective_exclude_keywords: str,
        index_depth: int,
        index_types: str | None,
        custom_content_extensions: str,
        custom_filename_extensions: str,
        source_type: str = "local",
    ) -> None:
        """
        フォルダ未指定かつ全 DB 検索 OFF のときは、検索対象フォルダを順次再インデックスする。
        有効対象があればそれを優先し、0 件なら登録済みフォルダ全体へフォールバックする。
        """
        target_paths = self.index_service.list_registered_search_target_paths(enabled_only=True, source_type=source_type)
        if not target_paths:
            target_paths = self.index_service.list_registered_search_target_paths(enabled_only=False, source_type=source_type)
        if not target_paths:
            return

        normalized_extensions = self.index_service._normalize_selected_extensions(
            index_types,
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
        )
        for target_path in target_paths:
            try:
                target = self.index_service._ensure_target(
                    full_path=target_path,
                    exclude_keywords=effective_exclude_keywords,
                    index_depth=index_depth,
                    selected_extensions=normalized_extensions,
                )
            except HTTPException as error:
                if error.status_code == status.HTTP_400_BAD_REQUEST:
                    continue
                raise
            effective_keywords = self.index_service._merge_exclude_keyword_strings(
                effective_exclude_keywords,
                str(target.get("exclude_keywords") or ""),
            )
            if not self.index_service._needs_refresh(
                target,
                refresh_window_minutes,
                effective_keywords,
                index_depth,
                normalized_extensions,
            ):
                continue
            try:
                self.index_service.ensure_fresh_target(
                    full_path=target_path,
                    refresh_window_minutes=refresh_window_minutes,
                    exclude_keywords=effective_keywords,
                    index_depth=index_depth,
                    types=index_types,
                )
            except HTTPException as error:
                if error.status_code == status.HTTP_400_BAD_REQUEST:
                    continue
                raise

    def _refresh_target_for_search(
        self,
        *,
        normalized_target_path: str,
        refresh_window_minutes: int,
        effective_exclude_keywords: str,
        index_depth: int,
        index_types: str | None,
        custom_content_extensions: str,
        custom_filename_extensions: str,
    ) -> dict[str, bool]:
        """
        既存インデックスがあるフォルダは既存結果を優先し、必要な再更新だけをバックグラウンドへ回す。
        初回検索や未インデックス状態では従来どおり同期インデックスを行う。
        """
        normalized_extensions = self.index_service._normalize_selected_extensions(
            index_types,
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
        )
        effective_target_path = (
            self.index_service._resolve_enabled_target_covering_path(
                normalized_target_path,
                source_type="web" if self.index_service._is_web_url(normalized_target_path) else "local",
            )
            or normalized_target_path
        )
        try:
            target = self.index_service._ensure_target(
                full_path=effective_target_path,
                exclude_keywords=effective_exclude_keywords,
                index_depth=index_depth,
                selected_extensions=normalized_extensions,
            )
        except HTTPException as error:
            # 既存インデックスだけでも検索できるよう、到達不能/未接続パスでは再更新を諦めて現在の DB を使う。
            if error.status_code == status.HTTP_400_BAD_REQUEST:
                return {"used_existing_index": True, "background_refresh_scheduled": False}
            raise
        effective_keywords = self.index_service._merge_exclude_keyword_strings(
            effective_exclude_keywords,
            str(target.get("exclude_keywords") or ""),
        )
        needs_refresh = self.index_service._needs_refresh(
            target,
            refresh_window_minutes,
            effective_keywords,
            index_depth,
            normalized_extensions,
        )
        has_existing_index = target.get("last_indexed_at") is not None
        if not needs_refresh:
            return {"used_existing_index": False, "background_refresh_scheduled": False}
        if not has_existing_index:
            try:
                self.index_service.ensure_fresh_target(
                    full_path=effective_target_path,
                    refresh_window_minutes=refresh_window_minutes,
                    exclude_keywords=effective_keywords,
                    index_depth=index_depth,
                    types=index_types,
                )
            except HTTPException as error:
                if error.status_code != status.HTTP_409_CONFLICT:
                    raise
            return {"used_existing_index": False, "background_refresh_scheduled": False}

        scheduled = self._schedule_background_refresh(
            normalized_target_path=effective_target_path,
            effective_exclude_keywords=effective_keywords,
            index_depth=index_depth,
            index_types=index_types,
        )
        return {"used_existing_index": True, "background_refresh_scheduled": scheduled}

    def _schedule_background_refresh(
        self,
        *,
        normalized_target_path: str,
        effective_exclude_keywords: str,
        index_depth: int,
        index_types: str | None,
    ) -> bool:
        """
        同一条件の再インデックスは1本だけ裏で実行し、検索レスポンス自体は待たない。
        """
        normalized_index_types = index_types or ""
        refresh_key = (
            normalized_target_path,
            effective_exclude_keywords,
            index_depth,
            normalized_index_types,
        )
        with _BACKGROUND_REFRESH_LOCK:
            if refresh_key in _BACKGROUND_REFRESH_KEYS:
                return False
            last_scheduled_at = _BACKGROUND_REFRESH_LAST_SCHEDULED_AT.get(refresh_key)
            now = time_module.monotonic()
            if last_scheduled_at is not None and now - last_scheduled_at < BACKGROUND_REFRESH_RETRY_COOLDOWN_SECONDS:
                return False
            _BACKGROUND_REFRESH_KEYS.add(refresh_key)
            _BACKGROUND_REFRESH_LAST_SCHEDULED_AT[refresh_key] = now

        def run_refresh() -> None:
            connection: Connection | None = None
            try:
                connection = get_connection()
                index_service = IndexService(connection=connection)
                if index_service._is_running():
                    return
                index_service.ensure_fresh_target(
                    full_path=normalized_target_path,
                    refresh_window_minutes=0,
                    exclude_keywords=effective_exclude_keywords,
                    index_depth=index_depth,
                    types=normalized_index_types,
                )
            except HTTPException:
                pass
            finally:
                if connection is not None:
                    connection.close()
                with _BACKGROUND_REFRESH_LOCK:
                    _BACKGROUND_REFRESH_KEYS.discard(refresh_key)

        threading.Thread(
            target=run_refresh,
            name="search-background-refresh",
            daemon=True,
        ).start()
        return True

    def search_existing_index(self, params: IndexedSearchRequest) -> SearchResponse:
        """
        既存 DB だけを使って検索する。
        対象フォルダ配下を深さ無制限で絞り込むが、インデックス更新は行わない。
        """
        normalized_target_path = normalize_path_str(params.folder_path) if params.folder_path else ""
        app_settings = self.index_service.get_app_settings()
        excluded_keywords = self.index_service._parse_exclude_keywords(app_settings.exclude_keywords)
        search_params = SearchQueryParams(
            q=params.q,
            full_path=params.folder_path,
            search_all_enabled=True,
            index_depth=0,
            refresh_window_minutes=0,
            limit=params.limit,
            offset=params.offset,
        )
        return self._execute_search(
            params=search_params,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
            app_settings=app_settings,
            path_depth_limit=None,
        )

    def _execute_search(
        self,
        *,
        params: SearchQueryParams,
        normalized_target_path: str,
        excluded_keywords: list[str],
        app_settings,
        path_depth_limit: int | None,
    ) -> SearchResponse:
        """
        FTS / 正規表現の分岐だけをまとめ、共通前処理を再利用する。
        """
        if params.regex_enabled:
            return self._search_with_regex(
                params=params,
                normalized_target_path=normalized_target_path,
                excluded_keywords=excluded_keywords,
                app_settings=app_settings,
                path_depth_limit=path_depth_limit,
            )

        return self._search_with_fts(
            params=params,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
            app_settings=app_settings,
            path_depth_limit=path_depth_limit,
        )

    def record_click(self, file_id: int, query: str = "") -> int:
        """
        検索結果オープン時のアクセス数を 1 件加算して返す。
        """
        cursor = self.connection.execute(
            """
            UPDATE files
            SET click_count = click_count + 1
            WHERE id = ?
            RETURNING click_count
            """,
            (file_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="検索結果が見つかりません。")
        normalized_query = self._normalize_query_for_history(query)
        if normalized_query:
            self.connection.execute(
                """
                INSERT INTO search_query_clicks(normalized_query, file_id, click_count, last_clicked_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(normalized_query, file_id) DO UPDATE SET
                    click_count = click_count + 1,
                    last_clicked_at = CURRENT_TIMESTAMP
                """,
                (normalized_query, file_id),
            )
        self.connection.commit()
        return int(row["click_count"])

    def _normalize_query_for_history(self, query: str) -> str:
        """
        検索履歴のキーをUnicode正規化し、空白と大文字小文字の差を吸収する。
        """
        return " ".join(unicodedata.normalize("NFKC", query).casefold().split())

    def _search_with_fts(
        self,
        *,
        params: SearchQueryParams,
        normalized_target_path: str,
        excluded_keywords: list[str],
        app_settings,
        path_depth_limit: int | None,
    ) -> SearchResponse:
        """
        通常モードでは既存の FTS5 ベース全文検索を利用する。
        CTE を1回だけ評価し、COUNT と結果を同時に取得する。
        """
        fts_start = time_module.perf_counter()

        scoped_files_cte_sql, scoped_file_values = self._build_scoped_files_cte(
            normalized_target_path=normalized_target_path,
            search_all_enabled=params.search_all_enabled,
            path_depth_limit=path_depth_limit,
            types=params.types,
            date_field=params.date_field,
            created_from=params.created_from,
            created_to=params.created_to,
            custom_content_extensions=app_settings.custom_content_extensions,
            custom_filename_extensions=app_settings.custom_filename_extensions,
            source_type=params.source_type,
        )
        cte_elapsed = time_module.perf_counter() - fts_start
        logger.info("FTS: Scoped files CTE build time: %.3fs", cte_elapsed)

        normalized_query = params.q.strip()
        include_terms, exclude_terms = self._split_search_terms(normalized_query)
        expanded_include_terms = self._expand_include_terms_with_synonyms(include_terms, app_settings.synonym_groups)
        search_body = self._search_target_includes_body(params.search_target)
        search_filename = self._search_target_includes_filename(params.search_target)
        search_folder = self._search_target_includes_folder(params.search_target)

        matched_queries: list[str] = []
        query_values: list[object] = []
        for term_index, term_group in enumerate(expanded_include_terms):
            for term in term_group:
                escaped_term = self._escape_like_pattern(term.lower())
                if search_body and self._should_use_literal_term_search(term):
                    matched_queries.append(
                        f"""
                        SELECT
                            scoped_files.id AS file_id,
                            {term_index} AS term_index,
                            0 AS match_rank,
                            0.0 AS score,
                            NULL AS snippet,
                            file_segments.segment_type AS segment_type,
                            file_segments.content AS body_content
                        FROM scoped_files
                        JOIN file_segments ON file_segments.file_id = scoped_files.id
                        WHERE file_segments.segment_type = 'body'
                          AND lower(file_segments.content) LIKE ? ESCAPE '\\'
                        """
                    )
                    query_values.append(f"%{escaped_term}%")
                elif search_body:
                    body_fts_query = self._build_fts_content_query(self._quote_fts_term(term))
                    matched_queries.append(
                        f"""
                        SELECT
                            scoped_files.id AS file_id,
                            {term_index} AS term_index,
                            0 AS match_rank,
                            bm25(file_segments_fts) AS score,
                            snippet(file_segments_fts, 0, '<mark>', '</mark>', ' ... ', 36) AS snippet,
                            file_segments.segment_type AS segment_type,
                            file_segments.content AS body_content
                        FROM scoped_files
                        JOIN file_segments ON file_segments.file_id = scoped_files.id
                        JOIN file_segments_fts ON file_segments_fts.rowid = file_segments.id
                        WHERE file_segments.segment_type = 'body'
                          AND file_segments_fts MATCH ?
                        """
                    )
                    query_values.append(body_fts_query)

                    cjk_bigram_query = build_cjk_bigram_match_query(term)
                    if cjk_bigram_query is not None:
                        cjk_bigram_query = self._build_fts_content_query(cjk_bigram_query)
                        matched_queries.append(
                            f"""
                            SELECT
                                scoped_files.id AS file_id,
                                {term_index} AS term_index,
                                1 AS match_rank,
                                bm25(file_segments_fts) AS score,
                                NULL AS snippet,
                                file_segments.segment_type AS segment_type,
                                body_segments.content AS body_content
                            FROM scoped_files
                            JOIN file_segments ON file_segments.file_id = scoped_files.id
                            JOIN file_segments_fts ON file_segments_fts.rowid = file_segments.id
                            JOIN file_segments AS body_segments
                              ON body_segments.file_id = scoped_files.id
                             AND body_segments.segment_type = 'body'
                            WHERE file_segments.segment_type = 'cjk_bigram'
                              AND file_segments_fts MATCH ?
                            """
                        )
                        query_values.append(cjk_bigram_query)

                if search_filename:
                    if self._should_use_filename_fts(term):
                        matched_queries.append(
                            f"""
                            SELECT
                                scoped_files.id AS file_id,
                                {term_index} AS term_index,
                                2 AS match_rank,
                                1000000.0 AS score,
                                NULL AS snippet,
                                'filename' AS segment_type,
                                body_segments.content AS body_content
                            FROM scoped_files
                            JOIN files_name_fts ON files_name_fts.rowid = scoped_files.id
                            LEFT JOIN file_segments AS body_segments
                              ON body_segments.file_id = scoped_files.id
                             AND body_segments.segment_type = 'body'
                            WHERE files_name_fts MATCH ?
                            """
                        )
                        query_values.append(self._quote_fts_term(term))
                    else:
                        matched_queries.append(
                            f"""
                            SELECT
                                scoped_files.id AS file_id,
                                {term_index} AS term_index,
                                2 AS match_rank,
                                1000000.0 AS score,
                                NULL AS snippet,
                                'filename' AS segment_type,
                                body_segments.content AS body_content
                            FROM scoped_files
                            LEFT JOIN file_segments AS body_segments
                              ON body_segments.file_id = scoped_files.id
                             AND body_segments.segment_type = 'body'
                            WHERE lower(scoped_files.file_name) LIKE ? ESCAPE '\\'
                            """
                        )
                        query_values.append(f"%{escaped_term}%")

                    for metadata_column, segment_type, match_rank in (
                        ("obsidian_title", "obsidian_title", 3),
                        ("obsidian_aliases", "obsidian_alias", 4),
                    ):
                        matched_queries.append(
                            f"""
                            SELECT
                                scoped_files.id AS file_id,
                                {term_index} AS term_index,
                                {match_rank} AS match_rank,
                                1000000.0 AS score,
                                NULL AS snippet,
                                '{segment_type}' AS segment_type,
                                body_segments.content AS body_content
                            FROM scoped_files
                            LEFT JOIN file_segments AS body_segments
                              ON body_segments.file_id = scoped_files.id
                             AND body_segments.segment_type = 'body'
                            WHERE lower(scoped_files.{metadata_column}) LIKE ? ESCAPE '\\'
                            """
                        )
                        query_values.append(f"%{escaped_term}%")

        prep_elapsed = time_module.perf_counter() - fts_start - cte_elapsed
        logger.info("FTS: Query preparation time: %.3fs", prep_elapsed)

        file_items: list[SearchResultItem] = []
        order_by_clause = self._build_order_by_clause(
            sort_by=params.sort_by,
            sort_order=params.sort_order,
            table_alias="scoped_files",
        )
        paged_order_by_clause = self._build_paged_order_by_clause(
            sort_by=params.sort_by,
            sort_order=params.sort_order,
            table_alias="paged_matches",
        )
        highlight_terms = self._flatten_highlight_terms(expanded_include_terms)

        if matched_queries:
            matched_files_cte = f"""
                {scoped_files_cte_sql},
                query_affinity AS (
                    SELECT
                        file_id,
                        (1.0 * click_count / (click_count + 2.0))
                        * (1.0 / (1.0 + MAX(strftime('%s', 'now') - strftime('%s', last_clicked_at), 0.0) / 2592000.0))
                        AS query_click_score
                    FROM search_query_clicks
                    WHERE normalized_query = ?
                ),
                matched_terms AS (
                    {" UNION ALL ".join(matched_queries)}
                ),
                matching_files AS (
                    SELECT
                        matched_terms.file_id,
                        CASE
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'filename' THEN term_index END) = {len(expanded_include_terms)}
                                 AND lower(substr(scoped_files.file_name, 1, length(scoped_files.file_name) - length(scoped_files.file_ext))) = ?
                            THEN 8
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'filename' THEN term_index END) = {len(expanded_include_terms)}
                                 AND lower(scoped_files.file_name) LIKE ? ESCAPE '\\'
                            THEN 7
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'filename' THEN term_index END) = {len(expanded_include_terms)}
                            THEN 6
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'obsidian_title' THEN term_index END) = {len(expanded_include_terms)}
                                 AND lower(scoped_files.obsidian_title) = ?
                            THEN 5
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'obsidian_title' THEN term_index END) = {len(expanded_include_terms)}
                            THEN 4
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'obsidian_alias' THEN term_index END) = {len(expanded_include_terms)}
                            THEN 3
                            WHEN COUNT(DISTINCT CASE WHEN segment_type = 'filename' THEN term_index END) > 0
                            THEN 2
                            WHEN COUNT(DISTINCT CASE WHEN segment_type IN ('obsidian_title', 'obsidian_alias') THEN term_index END) > 0
                            THEN 1
                            ELSE 0
                        END AS filename_match_level
                    FROM matched_terms
                    JOIN scoped_files ON scoped_files.id = matched_terms.file_id
                    GROUP BY matched_terms.file_id
                    HAVING COUNT(DISTINCT term_index) = {len(expanded_include_terms)}
                ),
                ranked_matches AS (
                    SELECT
                        matched_terms.file_id,
                        matched_terms.match_rank,
                        matched_terms.score,
                        matched_terms.snippet,
                        matched_terms.segment_type,
                        matched_terms.body_content,
                        matching_files.filename_match_level,
                        ROW_NUMBER() OVER (
                            PARTITION BY matched_terms.file_id
                            ORDER BY matched_terms.match_rank, matched_terms.score, matched_terms.file_id
                        ) AS rn
                    FROM matched_terms
                    JOIN matching_files ON matching_files.file_id = matched_terms.file_id
                ),
                filtered AS (
                    SELECT
                        ranked_matches.*,
                        11 - CAST(
                            CUME_DIST() OVER (ORDER BY match_rank, score) * 10 + 0.999999
                            AS INTEGER
                        ) AS relevance_bucket
                    FROM ranked_matches
                    WHERE rn = 1
                )
            """
            filename_phrase = f"%{self._escape_like_pattern(normalized_query.lower())}%"
            all_query_values = [
                *scoped_file_values,
                self._normalize_query_for_history(normalized_query),
                *query_values,
                normalized_query.lower(),
                filename_phrase,
                normalized_query.lower(),
            ]
            # フォルダ検索が有効、または除外条件がある場合は、全件を一旦取得して Python 側で処理する必要がある
            should_fetch_all_files = (
                search_folder
                or exclude_terms
                or (not normalized_target_path and excluded_keywords)
            )

            exec_start = time_module.perf_counter()
            if should_fetch_all_files:
                # 全件取得モード
                db_start = time_module.perf_counter()
                cursor = self.connection.execute(
                    f"""
                    {matched_files_cte}
                    SELECT
                        scoped_files.id AS file_id,
                        'file' AS result_kind,
                        scoped_files.file_name,
                        scoped_files.normalized_path,
                        scoped_files.file_ext,
                        scoped_files.created_at,
                        scoped_files.mtime,
                        scoped_files.click_count,
                        scoped_files.obsidian_click_count,
                        scoped_files.obsidian_rank_score,
                        scoped_files.has_obsidian_top_tag,
                        scoped_files.source_type,
                        filtered.snippet,
                        filtered.segment_type,
                        filtered.body_content,
                        filtered.filename_match_level,
                        filtered.relevance_bucket,
                        {self._build_utility_score_expression('scoped_files')} AS utility_score,
                        COALESCE(query_affinity.query_click_score, 0.0) AS query_click_score
                    FROM filtered
                    JOIN scoped_files ON scoped_files.id = filtered.file_id
                    LEFT JOIN query_affinity ON query_affinity.file_id = scoped_files.id
                    ORDER BY {order_by_clause}
                    """,
                    tuple(all_query_values),
                )
                db_elapsed = time_module.perf_counter() - db_start
                logger.info("FTS: SQL cursor creation time (all file search): %.3fs", db_elapsed)

                process_start = time_module.perf_counter()
                for row in cursor:
                    if self._should_exclude_search_result(
                        target_path=normalized_target_path,
                        candidate_path=str(row["normalized_path"]),
                        excluded_keywords=excluded_keywords,
                    ):
                        continue
                    if self._matches_excluded_search_terms(
                        file_name=str(row["file_name"]),
                        body_content=str(row["body_content"] or ""),
                        folder_path=self._resolve_folder_path(str(row["normalized_path"]), str(row["file_name"])),
                        exclude_terms=exclude_terms,
                    ):
                        continue
                    file_items.append(
                        self._build_search_result_item(
                            row=row,
                            normalized_target_path=normalized_target_path,
                            highlight_terms=highlight_terms,
                            include_snippets=params.include_snippets,
                        )
                    )
                process_elapsed = time_module.perf_counter() - process_start
                logger.info("FTS: Result fetch/filter/build time (all): %.3fs (matched=%d)", process_elapsed, len(file_items))

                exec_elapsed = time_module.perf_counter() - exec_start
                logger.info("FTS: Total execution and fetching time (all): %.3fs", exec_elapsed)

                if not search_folder:
                    # フォルダ検索不要なら、ここでページングして返す
                    page_items = file_items[params.offset : params.offset + params.limit]
                    has_more = params.offset + len(page_items) < len(file_items)
                    return SearchResponse(
                        total=len(file_items),
                        items=page_items,
                        has_more=has_more,
                        next_offset=params.offset + len(page_items) if has_more else None,
                    )
            else:
                # 高速ページングモード
                paged_query_values = [*all_query_values, params.limit + 1, params.offset]

                db_start = time_module.perf_counter()
                rows = self.connection.execute(
                    f"""
                    {matched_files_cte},
                    total_count AS (
                        SELECT COUNT(*) AS total
                        FROM filtered
                    ),
                    paged_matches AS (
                        SELECT
                            scoped_files.id AS file_id,
                            'file' AS result_kind,
                            scoped_files.file_name,
                            scoped_files.normalized_path,
                            scoped_files.file_ext,
                            scoped_files.created_at,
                            scoped_files.mtime,
                            scoped_files.click_count,
                            scoped_files.obsidian_click_count,
                            scoped_files.obsidian_rank_score,
                            scoped_files.has_obsidian_top_tag,
                            scoped_files.source_type,
                            filtered.snippet,
                            filtered.segment_type,
                            filtered.body_content,
                            filtered.filename_match_level,
                            filtered.relevance_bucket,
                            {self._build_utility_score_expression('scoped_files')} AS utility_score,
                            COALESCE(query_affinity.query_click_score, 0.0) AS query_click_score,
                            filtered.match_rank,
                            filtered.score
                        FROM filtered
                        JOIN scoped_files ON scoped_files.id = filtered.file_id
                        LEFT JOIN query_affinity ON query_affinity.file_id = scoped_files.id
                        ORDER BY {order_by_clause}
                        LIMIT ? OFFSET ?
                    )
                    SELECT
                        paged_matches.file_id,
                        paged_matches.result_kind,
                        paged_matches.file_name,
                        paged_matches.normalized_path,
                        paged_matches.file_ext,
                        paged_matches.created_at,
                        paged_matches.mtime,
                        paged_matches.click_count,
                        paged_matches.obsidian_click_count,
                        paged_matches.obsidian_rank_score,
                        paged_matches.has_obsidian_top_tag,
                        paged_matches.source_type,
                        paged_matches.snippet,
                        paged_matches.segment_type,
                        paged_matches.body_content,
                        paged_matches.filename_match_level,
                        paged_matches.relevance_bucket,
                        paged_matches.utility_score,
                        paged_matches.query_click_score,
                        total_count.total
                    FROM total_count
                        LEFT JOIN paged_matches ON 1 = 1
                    ORDER BY {paged_order_by_clause}
                    """,
                    tuple(paged_query_values),
                ).fetchall()
                db_elapsed = time_module.perf_counter() - db_start
                logger.info("FTS: SQL execution time (count + paged file search): %.3fs", db_elapsed)

                proc_start = time_module.perf_counter()
                total = int(rows[0]["total"]) if rows else 0
                page_rows = [row for row in rows if row["file_id"] is not None]
                has_more = len(page_rows) > params.limit
                visible_rows = page_rows[: params.limit]
                items = [
                    self._build_search_result_item(
                        row=row,
                        normalized_target_path=normalized_target_path,
                        highlight_terms=highlight_terms,
                        include_snippets=params.include_snippets,
                    )
                    for row in visible_rows
                ]
                proc_elapsed = time_module.perf_counter() - proc_start
                logger.info(
                    "FTS: Result processing time: %.3fs (rows=%d, visible=%d, total=%d)",
                    proc_elapsed,
                    len(page_rows),
                    len(visible_rows),
                    total,
                )

                exec_elapsed = time_module.perf_counter() - exec_start
                logger.info("FTS: Total execution and fetching time (paged): %.3fs", exec_elapsed)

                return SearchResponse(
                    total=total,
                    items=items,
                    has_more=has_more,
                    next_offset=params.offset + len(items) if has_more else None,
                )

        # フォルダ検索の処理（search_folder が True の場合）
        if not search_folder:
            return SearchResponse(total=0, items=[])

        folder_items = self._search_folder_results(
            scoped_files_cte_sql=scoped_files_cte_sql,
            scoped_file_values=scoped_file_values,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
            include_terms=include_terms,
            exclude_terms=exclude_terms,
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        merged_items = self._sort_search_result_items(
            [*file_items, *folder_items],
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        page_items = merged_items[params.offset : params.offset + params.limit]
        has_more = params.offset + len(page_items) < len(merged_items)
        return SearchResponse(
            total=len(merged_items),
            items=page_items,
            has_more=has_more,
            next_offset=params.offset + len(page_items) if has_more else None,
        )

    def _search_with_regex(
        self,
        *,
        params: SearchQueryParams,
        normalized_target_path: str,
        excluded_keywords: list[str],
        app_settings,
        path_depth_limit: int | None,
    ) -> SearchResponse:
        """
        正規表現モードでは Python の re で本文とファイル名を評価する。
        イテレータで逐次処理し、メモリ使用量を抑える。
        """
        regex_start = time_module.perf_counter()
        scoped_files_cte_sql, values = self._build_scoped_files_cte(
            normalized_target_path=normalized_target_path,
            search_all_enabled=params.search_all_enabled,
            path_depth_limit=path_depth_limit,
            types=params.types,
            date_field=params.date_field,
            created_from=params.created_from,
            created_to=params.created_to,
            custom_content_extensions=app_settings.custom_content_extensions,
            custom_filename_extensions=app_settings.custom_filename_extensions,
            source_type=params.source_type,
        )
        cte_elapsed = time_module.perf_counter() - regex_start
        logger.info("Regex: Scoped files CTE build time: %.3fs", cte_elapsed)

        normalized_query = params.q.strip()
        include_terms, exclude_terms = self._split_search_terms(normalized_query)
        pattern = self._compile_regex(" ".join(include_terms))
        search_body = self._search_target_includes_body(params.search_target)
        search_filename = self._search_target_includes_filename(params.search_target)
        search_folder = self._search_target_includes_folder(params.search_target)
        cursor = self.connection.execute(
            f"""
            {scoped_files_cte_sql}
            SELECT
                scoped_files.id AS file_id,
                scoped_files.file_name,
                scoped_files.normalized_path,
                scoped_files.file_ext,
                scoped_files.created_at,
                scoped_files.mtime,
                scoped_files.click_count,
                scoped_files.obsidian_click_count,
                scoped_files.obsidian_rank_score,
                scoped_files.has_obsidian_top_tag,
                scoped_files.source_type,
                file_segments.content
            FROM scoped_files
            LEFT JOIN file_segments
                ON file_segments.file_id = scoped_files.id
               AND file_segments.segment_type = 'body'
            ORDER BY {self._build_regex_order_by_clause(
                sort_by=params.sort_by,
                sort_order=params.sort_order,
                table_alias="scoped_files",
            )}
            """,
            tuple(values),
        )

        exec_elapsed = time_module.perf_counter() - regex_start - cte_elapsed
        logger.info("Regex: DB execution time: %.3fs", exec_elapsed)

        proc_start = time_module.perf_counter()

        file_items: list[SearchResultItem] = []
        folder_items_by_path: dict[str, SearchResultItem] = {}
        for row in cursor:
            normalized_path = str(row["normalized_path"])
            if self.index_service._should_exclude_path(normalize_path(normalized_path), excluded_keywords):
                continue

            file_name = str(row["file_name"])
            folder_path = self._resolve_folder_path(normalized_path, file_name)
            content = str(row["content"] or "")
            content_match = pattern.search(content) if search_body else None
            file_name_match = pattern.search(file_name) if search_filename else None
            folder_path_match = pattern.search(folder_path) if search_folder else None
            if content_match is None and file_name_match is None and folder_path_match is None:
                continue
            if self._matches_excluded_search_terms(
                file_name=file_name,
                body_content=content,
                folder_path=folder_path,
                exclude_terms=exclude_terms,
            ):
                continue

            if content_match is not None or file_name_match is not None:
                file_items.append(
                    SearchResultItem(
                        file_id=int(row["file_id"]),
                        result_kind="file",
                        source_type="web" if str(row["source_type"] or "local") == "web" else "local",
                        target_path=normalized_target_path,
                        file_name=file_name,
                        full_path=normalized_path,
                        file_ext=str(row["file_ext"]),
                        created_at=datetime.fromtimestamp(float(row["created_at"]), tz=UTC),
                        mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                        click_count=int(row["click_count"] or 0) + int(row["obsidian_click_count"] or 0),
                        has_obsidian_top_tag=bool(row["has_obsidian_top_tag"]),
                        filename_match_priority=file_name_match is not None,
                        filename_match_level=2 if file_name_match is not None else 0,
                        relevance_bucket=10,
                        utility_score=self._calculate_utility_score(
                            click_count=int(row["click_count"] or 0) + int(row["obsidian_click_count"] or 0),
                            obsidian_rank_score=float(row["obsidian_rank_score"] or 0.0),
                            mtime=float(row["mtime"]),
                        ),
                        snippet=(
                            self._build_regex_snippet(
                                content=content,
                                file_name=file_name,
                                folder_path=folder_path,
                                content_match=content_match,
                                file_name_match=file_name_match,
                                folder_path_match=None,
                            )
                            if params.include_snippets
                            else ""
                        ),
                    )
                )

            if folder_path_match is not None and folder_path not in folder_items_by_path:
                folder_items_by_path[folder_path] = SearchResultItem(
                    file_id=-len(folder_items_by_path) - 1,
                    result_kind="folder",
                    source_type="local",
                    target_path=normalized_target_path,
                    file_name=self._resolve_result_display_name("folder", folder_path, folder_path),
                    full_path=folder_path,
                    file_ext="",
                    created_at=datetime.fromtimestamp(float(row["created_at"]), tz=UTC),
                    mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                    click_count=0,
                    snippet=(
                        self._build_regex_snippet(
                            content=content,
                            file_name=file_name,
                            folder_path=folder_path,
                            content_match=None,
                            file_name_match=None,
                            folder_path_match=folder_path_match,
                        )
                        if params.include_snippets
                        else ""
                    ),
                )

        all_items = self._sort_search_result_items(
            [*file_items, *folder_items_by_path.values()],
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        page_items = all_items[params.offset : params.offset + params.limit]
        has_more = params.offset + len(page_items) < len(all_items)

        proc_elapsed = time_module.perf_counter() - proc_start
        logger.info(
            "Regex: Result processing and matching time: %.3fs (total=%d, visible=%d)",
            proc_elapsed,
            len(all_items),
            len(page_items),
        )

        return SearchResponse(
            total=len(all_items),
            items=page_items,
            has_more=has_more,
            next_offset=params.offset + len(page_items) if has_more else None,
        )

    def _schedule_obsidian_access_sync(self) -> None:
        """
        Obsidian の利用状況同期は検索完了後に非同期で行い、次回検索の順位へ反映する。
        """
        global _OBSIDIAN_SYNC_RUNNING
        with _OBSIDIAN_SYNC_LOCK:
            if _OBSIDIAN_SYNC_RUNNING:
                return
            _OBSIDIAN_SYNC_RUNNING = True

        def run_sync() -> None:
            connection: Connection | None = None
            try:
                connection = get_connection()
                initialize_schema(connection)
                SearchService(connection=connection)._sync_obsidian_access_counts()
            finally:
                if connection is not None:
                    connection.close()
                global _OBSIDIAN_SYNC_RUNNING
                with _OBSIDIAN_SYNC_LOCK:
                    _OBSIDIAN_SYNC_RUNNING = False

        threading.Thread(target=run_sync, name="search-obsidian-sync", daemon=True).start()

    def _sync_obsidian_access_counts(self) -> None:
        """
        sidebar-explorer の data.json からアクセス数と重要度スコアを files へ同期する。
        """
        configured_path = self.index_service.get_app_settings().obsidian_sidebar_explorer_data_path
        if not configured_path:
            return

        data_path = Path(configured_path)
        if not data_path.exists():
            # 指定されたパスが存在しない場合は何もしない
            return

        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 読み取り失敗時は静かに終了する
            return

        raw_metrics = payload.get("fileMetrics") or payload.get("files") or payload.get("metrics")
        raw_access_counts = payload.get("accessCounts")
        if raw_metrics is not None and not isinstance(raw_metrics, dict):
            raw_metrics = None
        if raw_metrics is None and not isinstance(raw_access_counts, dict):
            return

        # .obsidian ディレクトリの親を Vault ルートとして特定する。
        data_path_abs = data_path.resolve()
        vault_root_path: Path | None = None
        for parent in data_path_abs.parents:
            if (parent / ".obsidian").is_dir():
                vault_root_path = parent
                break

        if vault_root_path is None:
            # Vaultルート（.obsidianの親）が特定できない場合は、不正な構造とみなして終了する
            return

        vault_root = normalize_path_str(vault_root_path)
        prefix_start, prefix_end = get_descendant_path_range(vault_root)
        self.connection.execute(
            """
            UPDATE files
            SET obsidian_click_count = 0,
                obsidian_rank_score = 0.0
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        )

        updates: list[tuple[int, float, str]] = []
        raw_items = raw_metrics if isinstance(raw_metrics, dict) else raw_access_counts
        for relative_path, raw_value in raw_items.items():
            if not isinstance(relative_path, str):
                continue
            metrics = raw_value if isinstance(raw_value, dict) else {"accessCount": raw_value}
            access_count = self._coerce_non_negative_int(
                metrics.get("accessCount", raw_access_counts.get(relative_path) if isinstance(raw_access_counts, dict) else 0)
            )
            rank_score = self._calculate_obsidian_rank_score(metrics)
            normalized_full_path = normalize_path_str(Path(vault_root) / Path(relative_path))
            updates.append((access_count, rank_score, normalized_full_path))

        if updates:
            self.connection.executemany(
                "UPDATE files SET obsidian_click_count = ?, obsidian_rank_score = ? WHERE normalized_path = ?",
                updates,
            )
        self.connection.commit()
        logger.info("Synced %d Obsidian ranking metrics from %s", len(updates), vault_root)

    def _calculate_obsidian_rank_score(self, metrics: dict[str, object]) -> float:
        """
        Obsidian ノートの重要度を、検索語一致を壊さない補助スコアへ正規化する。
        """
        now_ms = time_module.time() * 1000
        access_score = self._log_score(metrics.get("accessCount"))
        backlink_score = self._log_score(metrics.get("backlinkCount"))
        last_opened_score = self._recency_score(metrics.get("lastOpenedAt"), now_ms, half_life_days=21)
        modified_score = self._recency_score(metrics.get("modifiedAt"), now_ms, half_life_days=45)
        outgoing_score = self._log_score(metrics.get("outgoingLinkCount"))
        attachment_score = self._log_score(metrics.get("attachmentCount"))
        heading_score = self._log_score(metrics.get("headingCount"))
        tag_score = self._log_score(metrics.get("tagCount"))

        return round(
            OBSIDIAN_RANK_SCORE_SCALE
            * (
                0.28 * backlink_score
                + 0.22 * access_score
                + 0.16 * last_opened_score
                + 0.1 * modified_score
                + 0.08 * outgoing_score
                + 0.06 * tag_score
                + 0.05 * heading_score
                + 0.05 * attachment_score
            ),
            6,
        )

    def _log_score(self, value: object) -> float:
        return min(1.0, math.log1p(self._coerce_non_negative_int(value)) / math.log1p(50))

    def _recency_score(self, value: object, now_ms: float, *, half_life_days: int) -> float:
        timestamp = self._coerce_non_negative_float(value)
        if timestamp <= 0 or timestamp > now_ms:
            return 0.0
        age_days = (now_ms - timestamp) / (1000 * 60 * 60 * 24)
        return 0.5 ** (age_days / half_life_days)

    def _coerce_non_negative_int(self, value: object) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0

    def _coerce_non_negative_float(self, value: object) -> float:
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _resolve_snippet(
        self,
        *,
        snippet: object,
        file_name: str,
        segment_type: str = "filename",
        body_content: object = None,
        folder_path: str = "",
        query: str = "",
        highlight_terms: list[str] | None = None,
    ) -> str:
        if segment_type == "body":
            literal_snippet = self._build_literal_snippet(
                content=str(body_content or ""),
                highlight_terms=highlight_terms or self._split_search_terms(query)[0],
            )
            if literal_snippet is not None:
                return literal_snippet
        if segment_type == "cjk_bigram":
            literal_snippet = self._build_literal_snippet(
                content=str(body_content or ""),
                highlight_terms=highlight_terms or self._split_search_terms(query)[0],
            )
            if literal_snippet is not None:
                return literal_snippet
        if segment_type == "folder":
            literal_snippet = self._build_literal_snippet(
                content=folder_path,
                highlight_terms=highlight_terms or self._split_search_terms(query)[0],
            )
            if literal_snippet is not None:
                return f"フォルダー名一致: {literal_snippet}"
        if isinstance(snippet, str) and snippet.strip():
            return snippet
        escaped_name = escape(file_name)
        return (
            f"ファイル名一致: <mark>{escaped_name}</mark>。"
            " 本文中には検索語の直接一致が見つからなかったため、"
            "ファイル名ベースの候補として表示しています。"
        )

    def _build_literal_snippet(self, *, content: str, highlight_terms: list[str]) -> str | None:
        """
        本文ヒットでは、検索語をなるべく同じ抜粋に含めてハイライト表示する。
        """
        if not content or not highlight_terms:
            return None

        lowered_content = content.lower()
        term_ranges: list[tuple[int, int]] = []
        for term in highlight_terms:
            start = lowered_content.find(term.lower())
            if start < 0:
                continue
            term_ranges.append((start, start + len(term)))

        if not term_ranges:
            return None

        start = min(item[0] for item in term_ranges)
        end = max(item[1] for item in term_ranges)
        snippet_start = max(start - 48, 0)
        snippet_end = min(end + 48, len(content))
        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(content) else ""
        snippet_text = content[snippet_start:snippet_end]
        highlighted = escape(snippet_text)
        for term in sorted(set(highlight_terms), key=len, reverse=True):
            highlighted = re.sub(
                re.escape(escape(term)),
                lambda match: f"<mark>{match.group(0)}</mark>",
                highlighted,
                flags=re.IGNORECASE,
            )
        return f"{prefix}{highlighted}{suffix}"

    def _expand_include_terms_with_synonyms(self, include_terms: list[str], synonym_groups_text: str) -> list[list[str]]:
        """
        同義語リストに含まれる語は OR 条件の候補へ展開し、各入力語は「同じキーワード」として扱う。
        """
        synonym_groups = self.index_service._parse_synonym_groups(synonym_groups_text)
        expanded_terms: list[list[str]] = []
        for term in include_terms:
            normalized_term = term.casefold()
            matched_group = next(
                (group for group in synonym_groups if any(candidate.casefold() == normalized_term for candidate in group)),
                None,
            )
            if matched_group is None:
                expanded_terms.append([term])
                continue

            ordered_group = [term, *matched_group]
            seen: set[str] = set()
            unique_group: list[str] = []
            for candidate in ordered_group:
                normalized_candidate = candidate.casefold()
                if normalized_candidate in seen:
                    continue
                seen.add(normalized_candidate)
                unique_group.append(candidate)
            expanded_terms.append(unique_group)
        return expanded_terms

    def _flatten_highlight_terms(self, expanded_include_terms: list[list[str]]) -> list[str]:
        """
        スニペット生成では、入力語だけでなく同義語展開後の候補もまとめてハイライト対象にする。
        """
        seen: set[str] = set()
        highlight_terms: list[str] = []
        for group in expanded_include_terms:
            for term in group:
                normalized_term = term.casefold()
                if normalized_term in seen:
                    continue
                seen.add(normalized_term)
                highlight_terms.append(term)
        return highlight_terms

    def _escape_like_pattern(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _should_exclude_search_result(
        self,
        *,
        target_path: str,
        candidate_path: str,
        excluded_keywords: list[str],
    ) -> bool:
        """
        検索結果の除外判定は対象フォルダ配下の相対パスだけで行う。
        絶対パス上の祖先ディレクトリ名まで見ると、対象外の親フォルダ名で誤除外される。
        """
        if not excluded_keywords:
            return False
        if target_path.startswith(("http://", "https://")) or candidate_path.startswith(("http://", "https://")):
            lowered_candidate = candidate_path.lower()
            return any(keyword.lower() in lowered_candidate for keyword in excluded_keywords)
        if not target_path:
            return self.index_service._should_exclude_path(normalize_path(candidate_path), excluded_keywords)

        target_root = normalize_path(target_path)
        result_path = normalize_path(candidate_path)
        try:
            relative_path = result_path.relative_to(target_root)
        except ValueError:
            relative_path = result_path
        return self.index_service._should_exclude_path(relative_path, excluded_keywords)

    def _split_search_terms(self, value: str) -> tuple[list[str], list[str]]:
        """
        利用者入力を空白で区切り、通常語と `-keyword` の除外語へ分離する。
        `\\-keyword` は先頭ハイフンを含む通常語として扱う。
        ただし全語が `-` 始まりのときは従来互換のため通常語として扱う。
        """
        include_terms: list[str] = []
        exclude_terms: list[str] = []
        for term in (item for item in value.split() if item):
            if term.startswith("\\-"):
                include_terms.append(term[1:])
                continue
            if term.startswith("-") and len(term) > 1:
                exclude_terms.append(term[1:])
                continue
            include_terms.append(term)

        if include_terms:
            return include_terms, exclude_terms

        fallback_terms = [term for term in value.split() if term]
        return fallback_terms, []

    def _matches_excluded_search_terms(
        self,
        *,
        file_name: str,
        body_content: str,
        folder_path: str,
        exclude_terms: list[str],
    ) -> bool:
        """
        `-keyword` 指定の語がファイル名・フォルダーパス・本文に含まれる候補は除外する。
        """
        if not exclude_terms:
            return False

        lowered_file_name = file_name.lower()
        lowered_body_content = body_content.lower()
        lowered_folder_path = folder_path.lower()
        for term in exclude_terms:
            lowered_term = term.lower()
            if (
                lowered_term in lowered_file_name
                or lowered_term in lowered_body_content
                or lowered_term in lowered_folder_path
            ):
                return True
        return False

    def _build_folder_path_sql_expression(self, table_alias: str) -> str:
        """
        SQL 上で、ファイル自身を除いた親フォルダーパス部分を取り出す。
        """
        return (
            f"rtrim(substr({table_alias}.normalized_path, 1, "
            f"length({table_alias}.normalized_path) - length({table_alias}.file_name)), '/')"
        )

    def _resolve_folder_path(self, normalized_path: str, file_name: str) -> str:
        """
        正規化済みフルパスから、検索用の親フォルダーパスを取り出す。
        """
        if normalized_path.endswith(file_name):
            return normalized_path[: -len(file_name)].rstrip("/") or "/"
        parts = normalized_path.rsplit("/", 1)
        return parts[0] if len(parts) == 2 and parts[0] else "/"

    def _resolve_result_display_name(self, result_kind: str, full_path: str, file_name: str) -> str:
        """
        フォルダ結果ではフルパスではなく末尾名を表示名として返す。
        """
        if result_kind != "folder":
            return file_name
        trimmed = full_path.rstrip("/\\")
        if not trimmed:
            return full_path
        last_separator_index = max(trimmed.rfind("/"), trimmed.rfind("\\"))
        if last_separator_index < 0:
            return trimmed
        if last_separator_index == 0:
            return trimmed
        return trimmed[last_separator_index + 1 :]

    def _resolve_folder_path_for_result(self, result_kind: str, full_path: str, file_name: str) -> str:
        """
        結果種別に応じて、スニペットや除外判定に使うフォルダーパスを返す。
        """
        if result_kind == "folder":
            return full_path
        return self._resolve_folder_path(full_path, file_name)

    def _search_target_includes_body(self, search_target: str) -> bool:
        """
        検索種別が本文検索を含むかを返す。
        """
        return search_target in {"all", "body"}

    def _search_target_includes_filename(self, search_target: str) -> bool:
        """
        検索種別がファイル名検索を含むかを返す。
        """
        return search_target in {"all", "filename", "filename_and_folder"}

    def _search_target_includes_folder(self, search_target: str) -> bool:
        """
        検索種別がフォルダー名検索を含むかを返す。
        """
        return search_target in {"all", "folder", "filename_and_folder"}

    def _should_use_literal_term_search(self, term: str) -> bool:
        """
        先頭が `-` の語や `mp3` のような英数字混在語は FTS5 MATCH で取りこぼすことがあるため、
        LIKE ベースの文字列検索へ切り替える。
        """
        return term.startswith("-") or self._contains_ascii_letters_and_digits(term)

    def _contains_ascii_letters_and_digits(self, term: str) -> bool:
        """
        ASCII 英字と数字を両方含む検索語かどうかを返す。
        `mp3`, `h264`, `mp4a` などの語は SQLite の標準 tokenizer で安定しないため特別扱いする。
        """
        has_ascii_letter = any(("a" <= char.lower() <= "z") for char in term)
        has_digit = any(char.isdigit() for char in term)
        return has_ascii_letter and has_digit

    def _should_use_filename_fts(self, term: str) -> bool:
        """
        trigram FTS は 3 文字以上の部分一致で有効に使い、短すぎる語だけ LIKE へフォールバックする。
        """
        return len(term) >= 3

    def _quote_fts_term(self, term: str) -> str:
        escaped_term = term.replace('"', '""')
        return f'"{escaped_term}"'

    def _build_fts_content_query(self, query: str) -> str:
        """
        FTS5 の本文検索は content カラムだけへ限定し、segment_label 側の誤一致を避ける。
        """
        return f"content:({query})"

    def _build_common_filters(
        self,
        *,
        normalized_target_path: str,
        search_all_enabled: bool,
        path_depth_limit: int | None,
        types: str | None,
        date_field: str = "created",
        created_from: date | None = None,
        created_to: date | None = None,
        custom_content_extensions: str = "",
        custom_filename_extensions: str = "",
        source_type: str = "local",
    ) -> tuple[str, list[object]]:
        """
        検索モード共通のパス・階層・拡張子・日付フィルタを組み立てる。
        """
        filters: list[str] = []
        normalized_source_type = "web" if source_type == "web" else "local"
        filters.append(f"files.source_type = '{normalized_source_type}'")
        values: list[object] = []
        date_column = "files.created_at" if date_field == "created" else "files.mtime"

        if normalized_target_path:
            prefix_start, prefix_end = get_descendant_path_range(normalized_target_path)
            if normalized_source_type == "web":
                filters.append("(files.normalized_path = ? OR (files.normalized_path >= ? AND files.normalized_path < ?))")
                values.extend([normalized_target_path, prefix_start, prefix_end])
            else:
                filters.extend(["files.normalized_path >= ?", "files.normalized_path < ?"])
                values.extend([prefix_start, prefix_end])

            if path_depth_limit is not None:
                descendant_prefix = get_descendant_path_prefix(normalized_target_path)
                depth_expression = (
                    "(length(files.normalized_path) - length(replace(files.normalized_path, '/', '')))"
                    " - (length(?) - length(replace(?, '/', '')))"
                )
                filters.append(f"{depth_expression} <= ?")
                values.extend([descendant_prefix, descendant_prefix, path_depth_limit])
        elif not search_all_enabled:
            enabled_target_paths = self.index_service.list_registered_search_target_paths(enabled_only=True, source_type=source_type)
            target_paths = enabled_target_paths
            if not target_paths:
                target_paths = self.index_service.list_registered_search_target_paths(enabled_only=False, source_type=source_type)
            if not target_paths:
                return "0 = 1", values

            target_filters: list[str] = []
            for target_path in target_paths:
                prefix_start, prefix_end = get_descendant_path_range(target_path)
                target_filters.append("(files.normalized_path >= ? AND files.normalized_path < ?)")
                values.extend([prefix_start, prefix_end])
            filters.append(f"({' OR '.join(target_filters)})")

        if types:
            extensions = sorted(
                normalize_extension_filter(
                    types,
                    extra_content_extensions=tuple(self.index_service._parse_extension_entries(custom_content_extensions)),
                    extra_filename_extensions=tuple(self.index_service._parse_extension_entries(custom_filename_extensions)),
                )
            )
            if extensions:
                placeholders = ", ".join("?" for _ in extensions)
                filters.append(f"files.file_ext IN ({placeholders})")
                values.extend(extensions)

        if created_from is not None:
            filters.append(f"{date_column} >= ?")
            values.append(self._resolve_local_day_start_timestamp(created_from))

        if created_to is not None:
            filters.append(f"{date_column} < ?")
            values.append(self._resolve_local_day_end_exclusive_timestamp(created_to))

        if not filters:
            return "1 = 1", values

        return " AND ".join(filters), values

    def _build_scoped_files_cte(
        self,
        *,
        normalized_target_path: str,
        search_all_enabled: bool,
        path_depth_limit: int | None,
        types: str | None,
        date_field: str = "created",
        created_from: date | None = None,
        created_to: date | None = None,
        custom_content_extensions: str = "",
        custom_filename_extensions: str = "",
        source_type: str = "local",
    ) -> tuple[str, list[object]]:
        """
        フォルダ・階層・拡張子・日付の候補絞り込みを1回だけ行う scoped_files CTE を組み立てる。
        """
        where_clause, values = self._build_common_filters(
            normalized_target_path=normalized_target_path,
            search_all_enabled=search_all_enabled,
            path_depth_limit=path_depth_limit,
            types=types,
            date_field=date_field,
            created_from=created_from,
            created_to=created_to,
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
            source_type=source_type,
        )
        return (
            f"""
            WITH scoped_files AS (
                SELECT
                    files.id,
                    files.file_name,
                    files.normalized_path,
                    files.file_ext,
                    files.created_at,
                    files.mtime,
                    files.click_count,
                    files.obsidian_click_count,
                    files.obsidian_rank_score,
                    files.has_obsidian_top_tag,
                    files.obsidian_title,
                    files.obsidian_aliases,
                    files.source_type
                FROM files
                WHERE {where_clause}
            )
            """,
            values,
        )

    def _build_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str = "files") -> str:
        """
        FTS 検索は一致品質を優先しつつ、同順位内で指定列へ並び替える。
        """
        if sort_by == "default":
            return f"filtered.filename_match_level DESC, {table_alias}.has_obsidian_top_tag DESC, query_click_score DESC, filtered.relevance_bucket DESC, {self._build_utility_score_expression(table_alias)} DESC, {table_alias}.mtime DESC, {table_alias}.id DESC"
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"filtered.match_rank, filtered.score, {table_alias}.obsidian_rank_score DESC, {sort_column} {direction}, {table_alias}.id DESC"

    def _build_paged_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str) -> str:
        """
        ページング CTE の結果を、内部 LIMIT 適用時と同じ優先順位で返す。
        """
        if sort_by == "default":
            return f"{table_alias}.filename_match_level DESC, {table_alias}.has_obsidian_top_tag DESC, {table_alias}.query_click_score DESC, {table_alias}.relevance_bucket DESC, {table_alias}.utility_score DESC, {table_alias}.mtime DESC, {table_alias}.file_id DESC"
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"{table_alias}.match_rank, {table_alias}.score, {table_alias}.obsidian_rank_score DESC, {sort_column} {direction}, {table_alias}.file_id DESC"

    def _build_combined_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str) -> str:
        """
        ファイル結果とフォルダ結果をまとめた集合を、一致品質と指定列で並び替える。
        """
        if sort_by == "default":
            return f"{table_alias}.has_obsidian_top_tag DESC, {table_alias}.click_count DESC, {table_alias}.mtime DESC, {table_alias}.match_rank, {table_alias}.score, {table_alias}.file_id DESC"
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"{table_alias}.match_rank, {table_alias}.score, {table_alias}.obsidian_rank_score DESC, {sort_column} {direction}, {table_alias}.file_id DESC"

    def _build_regex_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str = "files") -> str:
        """
        正規表現検索は DB 側で指定列順に走査し、結果の表示順と一致させる。
        """
        if sort_by == "default":
            return f"{table_alias}.has_obsidian_top_tag DESC, ({table_alias}.click_count + {table_alias}.obsidian_click_count) DESC, {table_alias}.mtime DESC, {table_alias}.id DESC"
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"{table_alias}.obsidian_rank_score DESC, {sort_column} {direction}, {table_alias}.id DESC"

    def _resolve_sort_column(self, sort_by: str, *, table_alias: str = "files") -> str:
        """
        並び替えキーを SQL の安全な固定列へ解決する。
        """
        if sort_by == "created":
            return f"{table_alias}.created_at"
        if sort_by == "click_count":
            return f"({table_alias}.click_count + {table_alias}.obsidian_click_count)"
        return f"{table_alias}.mtime"

    def _build_utility_score_expression(self, table_alias: str) -> str:
        """
        アクセス数を飽和させ、Obsidian重要度と90日半減相当の更新鮮度を合成する。
        """
        clicks = f"({table_alias}.click_count + {table_alias}.obsidian_click_count)"
        popularity = f"(1.0 * {clicks} / ({clicks} + 10.0))"
        obsidian_importance = f"MIN(MAX({table_alias}.obsidian_rank_score / 1000.0, 0.0), 1.0)"
        recency = f"(1.0 / (1.0 + MAX(strftime('%s', 'now') - {table_alias}.mtime, 0.0) / 7776000.0))"
        return f"(0.55 * {popularity} + 0.25 * {obsidian_importance} + 0.20 * {recency})"

    def _calculate_utility_score(self, *, click_count: int, obsidian_rank_score: float, mtime: float) -> float:
        """
        SQL版と同じ利用価値スコアを、正規表現検索などPython側の並び替え用に計算する。
        """
        popularity = click_count / (click_count + 10.0)
        obsidian_importance = min(max(obsidian_rank_score / 1000.0, 0.0), 1.0)
        age_seconds = max(time_module.time() - mtime, 0.0)
        recency = 1.0 / (1.0 + age_seconds / (90 * 24 * 60 * 60))
        return 0.55 * popularity + 0.25 * obsidian_importance + 0.20 * recency

    def _build_search_result_item(
        self,
        *,
        row,
        normalized_target_path: str,
        highlight_terms: list[str],
        include_snippets: bool,
    ) -> SearchResultItem:
        """
        DB 行から UI 用の検索結果モデルを組み立てる。
        """
        result_kind = str(row["result_kind"] or "file")
        try:
            source_type = str(row["source_type"] or "local")
        except (KeyError, IndexError):
            source_type = "local"
        full_path = str(row["normalized_path"])
        raw_name = str(row["file_name"])
        display_name = self._resolve_result_display_name(result_kind, full_path, raw_name)
        folder_path = self._resolve_folder_path_for_result(result_kind, full_path, raw_name)
        return SearchResultItem(
            file_id=int(row["file_id"]),
            result_kind="folder" if result_kind == "folder" else "file",
            source_type=source_type if source_type in {"web", "gantt"} else "local",
            target_path=normalized_target_path,
            file_name=display_name,
            full_path=full_path,
            file_ext=str(row["file_ext"]),
            created_at=datetime.fromtimestamp(float(row["created_at"]), tz=UTC),
            mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
            click_count=int(row["click_count"] or 0) + int(row["obsidian_click_count"] or 0),
            has_obsidian_top_tag=bool(row["has_obsidian_top_tag"]),
            filename_match_priority=int(row["filename_match_level"] or 0) >= 2,
            filename_match_level=int(row["filename_match_level"] or 0),
            relevance_bucket=int(row["relevance_bucket"] or 0),
            utility_score=float(row["utility_score"] or 0.0),
            query_click_score=float(row["query_click_score"] or 0.0),
            snippet=(
                self._resolve_snippet(
                    snippet=row["snippet"],
                    file_name=display_name,
                    segment_type=str(row["segment_type"] or "filename"),
                    body_content=row["body_content"],
                    folder_path=folder_path,
                    highlight_terms=highlight_terms,
                )
                if include_snippets
                else ""
            ),
        )

    def _sort_search_result_items(
        self,
        items: list[SearchResultItem],
        *,
        sort_by: str,
        sort_order: str,
    ) -> list[SearchResultItem]:
        """
        Python 側で構築した検索結果を UI 指定の並び順で安定ソートする。
        """
        if sort_by == "default":
            return sorted(
                items,
                key=lambda item: (
                    item.filename_match_level,
                    item.has_obsidian_top_tag,
                    item.query_click_score,
                    item.relevance_bucket,
                    item.utility_score,
                    item.mtime.timestamp(),
                    item.file_id,
                ),
                reverse=True,
            )

        reverse = sort_order == "desc"

        def key(item: SearchResultItem) -> tuple[float, int]:
            if sort_by == "click_count":
                return (float(item.click_count), item.file_id)
            if sort_by == "created":
                return (item.created_at.timestamp(), item.file_id)
            return (item.mtime.timestamp(), item.file_id)

        return sorted(items, key=key, reverse=reverse)

    def _search_folder_results(
        self,
        *,
        scoped_files_cte_sql: str,
        scoped_file_values: list[object],
        normalized_target_path: str,
        excluded_keywords: list[str],
        include_terms: list[str],
        exclude_terms: list[str],
        sort_by: str,
        sort_order: str,
    ) -> list[SearchResultItem]:
        """
        フォルダ名検索は SQL 側で親フォルダを集約し、Python 側の全件一意化を避ける。
        """
        lowered_terms = [term.lower() for term in include_terms if term]
        lowered_exclude_terms = [term.lower() for term in exclude_terms if term]
        folder_path_expression = self._build_folder_path_sql_expression("scoped_files")
        filters: list[str] = []
        values: list[object] = [*scoped_file_values]

        for term in lowered_terms:
            filters.append(f"lower({folder_path_expression}) LIKE ? ESCAPE '\\'")
            values.append(f"%{self._escape_like_pattern(term)}%")
        for term in lowered_exclude_terms:
            filters.append(f"lower({folder_path_expression}) NOT LIKE ? ESCAPE '\\'")
            values.append(f"%{self._escape_like_pattern(term)}%")

        where_clause = " AND ".join(filters) if filters else "1 = 1"
        folder_sql_start = time_module.perf_counter()
        try:
            rows = self.connection.execute(
                f"""
                {scoped_files_cte_sql}
                SELECT
                    {folder_path_expression} AS folder_path,
                    MAX(scoped_files.created_at) AS created_at,
                    MAX(scoped_files.mtime) AS mtime
                FROM scoped_files
                WHERE {where_clause}
                GROUP BY folder_path
                """,
                tuple(values),
            ).fetchall()
        finally:
            folder_sql_elapsed = time_module.perf_counter() - folder_sql_start
            logger.info("FTS: SQL execution time (folder search): %.3fs", folder_sql_elapsed)

        items = [
            SearchResultItem(
                file_id=-(index + 1),
                result_kind="folder",
                target_path=normalized_target_path,
                file_name=self._resolve_result_display_name("folder", folder_path, folder_path),
                full_path=folder_path,
                file_ext="",
                created_at=datetime.fromtimestamp(created_at, tz=UTC),
                mtime=datetime.fromtimestamp(mtime, tz=UTC),
                click_count=0,
                snippet=self._resolve_snippet(
                    snippet=None,
                    file_name=self._resolve_result_display_name("folder", folder_path, folder_path),
                    segment_type="folder",
                    folder_path=folder_path,
                    highlight_terms=include_terms,
                ),
            )
            for index, row in enumerate(rows)
            for folder_path in [str(row["folder_path"])]
            if not self._should_exclude_search_result(
                target_path=normalized_target_path,
                candidate_path=folder_path,
                excluded_keywords=excluded_keywords,
            )
            for created_at in [float(row["created_at"])]
            for mtime in [float(row["mtime"])]
        ]
        return self._sort_search_result_items(items, sort_by=sort_by, sort_order=sort_order)

    def _resolve_local_day_start_timestamp(self, value: date) -> float:
        """
        日付フィルタの開始境界はローカルタイムゾーンの 00:00:00 を使う。
        """
        return datetime.combine(value, time.min).astimezone().timestamp()

    def _resolve_local_day_end_exclusive_timestamp(self, value: date) -> float:
        """
        終了日はその翌日の 00:00:00 未満として inclusive に扱う。
        """
        next_day = value + timedelta(days=1)
        return datetime.combine(next_day, time.min).astimezone().timestamp()

    def _compile_regex(self, pattern: str) -> re.Pattern[str]:
        """
        不正な正規表現は 400 系エラーとして利用者に返す。
        """
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"正規表現が不正です: {error}",
            ) from error

    def _build_regex_snippet(
        self,
        *,
        content: str,
        file_name: str,
        folder_path: str,
        content_match: re.Match[str] | None,
        file_name_match: re.Match[str] | None,
        folder_path_match: re.Match[str] | None,
    ) -> str:
        """
        正規表現検索の結果用に、最初の一致箇所を短い抜粋として整形する。
        """
        if content_match is not None:
            snippet_start = max(content_match.start() - 48, 0)
            snippet_end = min(content_match.end() + 48, len(content))
            prefix = "..." if snippet_start > 0 else ""
            suffix = "..." if snippet_end < len(content) else ""
            before = escape(content[snippet_start:content_match.start()])
            matched = escape(content[content_match.start() : content_match.end()])
            after = escape(content[content_match.end() : snippet_end])
            return f"{prefix}{before}<mark>{matched}</mark>{after}{suffix}"

        if file_name_match is not None:
            start = file_name_match.start()
            end = file_name_match.end()
            return (
                "ファイル名一致: "
                f"{escape(file_name[:start])}<mark>{escape(file_name[start:end])}</mark>{escape(file_name[end:])}"
            )

        if folder_path_match is not None:
            start = folder_path_match.start()
            end = folder_path_match.end()
            return (
                "フォルダー名一致: "
                f"{escape(folder_path[:start])}<mark>{escape(folder_path[start:end])}</mark>{escape(folder_path[end:])}"
            )

        return self._resolve_snippet(snippet=None, file_name=file_name, folder_path=folder_path)
