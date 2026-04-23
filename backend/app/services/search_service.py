from datetime import UTC, date, datetime, time, timedelta
from html import escape
import json
from pathlib import Path
import re
from sqlite3 import Connection
import threading
import time as time_module

from fastapi import HTTPException, status

from app.db.connection import get_connection
from app.extractors.text_extractor import normalize_extension_filter
from app.models.search import IndexedSearchRequest, SearchQueryParams, SearchResponse, SearchResultItem
from app.services.cjk_bigram import build_cjk_bigram_match_query
from app.services.index_service import IndexService
from app.services.path_service import get_descendant_path_prefix, get_descendant_path_range, normalize_path, normalize_path_str

DEFAULT_OBSIDIAN_SIDEBAR_EXPLORER_DATA_PATH = Path(
    "/Users/mine/000_work/obsidian-dagnetz/.obsidian/plugins/obsidian-sidebar-explorer/data.json"
)
_BACKGROUND_REFRESH_LOCK = threading.Lock()
_BACKGROUND_REFRESH_KEYS: set[tuple[str, str, int, str]] = set()
_BACKGROUND_REFRESH_LAST_SCHEDULED_AT: dict[tuple[str, str, int, str], float] = {}
_OBSIDIAN_SYNC_LOCK = threading.Lock()
_OBSIDIAN_SYNC_RUNNING = False
BACKGROUND_REFRESH_RETRY_COOLDOWN_SECONDS = 30.0


class SearchService:
    """
    全文検索とファイル名検索をまとめて提供する。
    ユーザー入力は FTS5 構文としてではなく、通常の検索語として安全に扱う。
    """

    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()
        self.index_service = IndexService(connection=self.connection)

    def search(self, params: SearchQueryParams) -> SearchResponse:
        normalized_target_path = ""
        if params.full_path:
            normalized_target_path = normalize_path_str(params.full_path)
        app_settings = self.index_service.get_app_settings()
        effective_exclude_keywords = (
            params.exclude_keywords if params.exclude_keywords is not None else app_settings.exclude_keywords
        )
        excluded_keywords = self.index_service._parse_exclude_keywords(effective_exclude_keywords)
        refresh_flags = {"used_existing_index": False, "background_refresh_scheduled": False}
        if normalized_target_path and not params.search_all_enabled and not params.skip_refresh:
            refresh_flags = self._refresh_target_for_search(
                normalized_target_path=normalized_target_path,
                refresh_window_minutes=params.refresh_window_minutes,
                effective_exclude_keywords=effective_exclude_keywords,
                index_depth=params.index_depth,
                index_types=params.index_types,
                custom_content_extensions=app_settings.custom_content_extensions,
                custom_filename_extensions=app_settings.custom_filename_extensions,
            )

        response = self._execute_search(
            params=params,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
            app_settings=app_settings,
            path_depth_limit=params.index_depth,
        )
        self._schedule_obsidian_access_sync()
        return response.model_copy(update=refresh_flags)

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
            self.index_service._resolve_enabled_target_covering_path(normalized_target_path) or normalized_target_path
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
        normalized_target_path = normalize_path_str(params.folder_path)
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

    def record_click(self, file_id: int) -> int:
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
        self.connection.commit()
        return int(row["click_count"])

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
        scoped_files_cte_sql, scoped_file_values = self._build_scoped_files_cte(
            normalized_target_path=normalized_target_path,
            path_depth_limit=path_depth_limit,
            types=params.types,
            date_field=params.date_field,
            created_from=params.created_from,
            created_to=params.created_to,
            custom_content_extensions=app_settings.custom_content_extensions,
            custom_filename_extensions=app_settings.custom_filename_extensions,
        )

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

        file_items: list[SearchResultItem] = []
        order_by_clause = self._build_order_by_clause(
            sort_by=params.sort_by,
            sort_order=params.sort_order,
            table_alias="scoped_files",
        )
        highlight_terms = self._flatten_highlight_terms(expanded_include_terms)

        if matched_queries:
            matched_files_cte = f"""
                {scoped_files_cte_sql},
                matched_terms AS (
                    {" UNION ALL ".join(matched_queries)}
                ),
                matched_file_terms AS (
                    SELECT
                        file_id,
                        term_index
                    FROM matched_terms
                    GROUP BY file_id, term_index
                ),
                matching_files AS (
                    SELECT file_id
                    FROM matched_file_terms
                    GROUP BY file_id
                    HAVING COUNT(*) = {len(expanded_include_terms)}
                ),
                ranked_matches AS (
                    SELECT
                        matched_terms.file_id,
                        matched_terms.match_rank,
                        matched_terms.score,
                        matched_terms.snippet,
                        matched_terms.segment_type,
                        matched_terms.body_content,
                        ROW_NUMBER() OVER (
                            PARTITION BY matched_terms.file_id
                            ORDER BY matched_terms.match_rank, matched_terms.score, matched_terms.file_id
                        ) AS rn
                    FROM matched_terms
                    JOIN matching_files ON matching_files.file_id = matched_terms.file_id
                ),
                filtered AS (
                    SELECT * FROM ranked_matches WHERE rn = 1
                )
            """
            all_query_values = [*scoped_file_values, *query_values]
            should_fetch_all_files = (
                search_folder
                or exclude_terms
                or (not normalized_target_path and excluded_keywords)
            )

            if should_fetch_all_files:
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
                        filtered.snippet,
                        filtered.segment_type,
                        filtered.body_content
                    FROM filtered
                    JOIN scoped_files ON scoped_files.id = filtered.file_id
                    ORDER BY {order_by_clause}
                    """,
                    tuple(all_query_values),
                )
                file_items = []
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
                if not search_folder:
                    finalized_items = file_items
                    page_items = finalized_items[params.offset : params.offset + params.limit]
                    has_more = params.offset + len(page_items) < len(finalized_items)
                    return SearchResponse(
                        total=len(finalized_items),
                        items=page_items,
                        has_more=has_more,
                        next_offset=params.offset + len(page_items) if has_more else None,
                    )
            else:
                paged_query_values = [*all_query_values, params.limit + 1, params.offset]
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
                            filtered.snippet,
                            filtered.segment_type,
                            filtered.body_content,
                            filtered.match_rank,
                            filtered.score
                        FROM filtered
                        JOIN scoped_files ON scoped_files.id = filtered.file_id
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
                        paged_matches.snippet,
                        paged_matches.segment_type,
                        paged_matches.body_content,
                        total_count.total
                    FROM total_count
                    LEFT JOIN paged_matches ON 1 = 1
                    ORDER BY paged_matches.match_rank, paged_matches.score, paged_matches.mtime DESC
                    """,
                    tuple(paged_query_values),
                ).fetchall()

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
                    and not self._should_exclude_search_result(
                        target_path=normalized_target_path,
                        candidate_path=str(row["normalized_path"]),
                        excluded_keywords=excluded_keywords,
                    )
                    and not self._matches_excluded_search_terms(
                        file_name=str(row["file_name"]),
                        body_content=str(row["body_content"] or ""),
                        folder_path=self._resolve_folder_path(str(row["normalized_path"]), str(row["file_name"])),
                        exclude_terms=exclude_terms,
                    )
                ]
                return SearchResponse(
                    total=total,
                    items=items,
                    has_more=has_more,
                    next_offset=params.offset + len(items) if has_more else None,
                )

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
        scoped_files_cte_sql, values = self._build_scoped_files_cte(
            normalized_target_path=normalized_target_path,
            path_depth_limit=path_depth_limit,
            types=params.types,
            date_field=params.date_field,
            created_from=params.created_from,
            created_to=params.created_to,
            custom_content_extensions=app_settings.custom_content_extensions,
            custom_filename_extensions=app_settings.custom_filename_extensions,
        )
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
                        target_path=normalized_target_path,
                        file_name=file_name,
                        full_path=normalized_path,
                        file_ext=str(row["file_ext"]),
                        created_at=datetime.fromtimestamp(float(row["created_at"]), tz=UTC),
                        mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                        click_count=int(row["click_count"] or 0) + int(row["obsidian_click_count"] or 0),
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
        return SearchResponse(
            total=len(all_items),
            items=page_items,
            has_more=has_more,
            next_offset=params.offset + len(page_items) if has_more else None,
        )

    def _schedule_obsidian_access_sync(self) -> None:
        """
        Obsidian のアクセス数同期は検索完了後に非同期で行い、次回検索の順位へ反映する。
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
        sidebar-explorer の accessCounts を files.obsidian_click_count へ同期する。
        """
        configured_path = self.index_service.get_app_settings().obsidian_sidebar_explorer_data_path
        data_path = Path(configured_path) if configured_path else DEFAULT_OBSIDIAN_SIDEBAR_EXPLORER_DATA_PATH
        if not data_path.exists():
            return

        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        raw_access_counts = payload.get("accessCounts")
        if not isinstance(raw_access_counts, dict):
            return

        vault_root = normalize_path_str(data_path.parents[3])
        prefix_start, prefix_end = get_descendant_path_range(vault_root)
        self.connection.execute(
            """
            UPDATE files
            SET obsidian_click_count = 0
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        )

        updates: list[tuple[int, str]] = []
        for relative_path, raw_count in raw_access_counts.items():
            if not isinstance(relative_path, str):
                continue
            try:
                access_count = int(raw_count)
            except (TypeError, ValueError):
                continue
            normalized_full_path = normalize_path_str(Path(vault_root) / Path(relative_path))
            updates.append((max(access_count, 0), normalized_full_path))

        if updates:
            self.connection.executemany(
                "UPDATE files SET obsidian_click_count = ? WHERE normalized_path = ?",
                updates,
            )
        self.connection.commit()

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
        先頭が `-` の語は FTS5 MATCH では壊れやすいため、LIKE ベースの文字列検索へ切り替える。
        """
        return term.startswith("-")

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
        path_depth_limit: int | None,
        types: str | None,
        date_field: str = "created",
        created_from: date | None = None,
        created_to: date | None = None,
        custom_content_extensions: str = "",
        custom_filename_extensions: str = "",
    ) -> tuple[str, list[object]]:
        """
        検索モード共通のパス・階層・拡張子・日付フィルタを組み立てる。
        """
        filters: list[str] = []
        values: list[object] = []
        date_column = "files.created_at" if date_field == "created" else "files.mtime"

        if normalized_target_path:
            prefix_start, prefix_end = get_descendant_path_range(normalized_target_path)
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
        path_depth_limit: int | None,
        types: str | None,
        date_field: str = "created",
        created_from: date | None = None,
        created_to: date | None = None,
        custom_content_extensions: str = "",
        custom_filename_extensions: str = "",
    ) -> tuple[str, list[object]]:
        """
        フォルダ・階層・拡張子・日付の候補絞り込みを1回だけ行う scoped_files CTE を組み立てる。
        """
        where_clause, values = self._build_common_filters(
            normalized_target_path=normalized_target_path,
            path_depth_limit=path_depth_limit,
            types=types,
            date_field=date_field,
            created_from=created_from,
            created_to=created_to,
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
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
                    files.obsidian_click_count
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
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"filtered.match_rank, filtered.score, {sort_column} {direction}, {table_alias}.id DESC"

    def _build_combined_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str) -> str:
        """
        ファイル結果とフォルダ結果をまとめた集合を、一致品質と指定列で並び替える。
        """
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"{table_alias}.match_rank, {table_alias}.score, {sort_column} {direction}, {table_alias}.file_id DESC"

    def _build_regex_order_by_clause(self, *, sort_by: str, sort_order: str, table_alias: str = "files") -> str:
        """
        正規表現検索は DB 側で指定列順に走査し、結果の表示順と一致させる。
        """
        direction = "ASC" if sort_order == "asc" else "DESC"
        sort_column = self._resolve_sort_column(sort_by, table_alias=table_alias)
        return f"{sort_column} {direction}, {table_alias}.id DESC"

    def _resolve_sort_column(self, sort_by: str, *, table_alias: str = "files") -> str:
        """
        並び替えキーを SQL の安全な固定列へ解決する。
        """
        if sort_by == "created":
            return f"{table_alias}.created_at"
        if sort_by == "click_count":
            return f"({table_alias}.click_count + {table_alias}.obsidian_click_count)"
        return f"{table_alias}.mtime"

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
        full_path = str(row["normalized_path"])
        raw_name = str(row["file_name"])
        display_name = self._resolve_result_display_name(result_kind, full_path, raw_name)
        folder_path = self._resolve_folder_path_for_result(result_kind, full_path, raw_name)
        return SearchResultItem(
            file_id=int(row["file_id"]),
            result_kind="folder" if result_kind == "folder" else "file",
            target_path=normalized_target_path,
            file_name=display_name,
            full_path=full_path,
            file_ext=str(row["file_ext"]),
            created_at=datetime.fromtimestamp(float(row["created_at"]), tz=UTC),
            mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
            click_count=int(row["click_count"] or 0) + int(row["obsidian_click_count"] or 0),
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
