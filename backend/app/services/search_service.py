from datetime import UTC, datetime
from html import escape
import re
from sqlite3 import Connection

from fastapi import HTTPException, status

from app.db.connection import get_connection
from app.models.search import SearchQueryParams, SearchResponse, SearchResultItem
from app.services.cjk_bigram import build_cjk_bigram_match_query
from app.services.index_service import IndexService
from app.services.path_service import get_descendant_path_prefix, get_descendant_path_range, normalize_path, normalize_path_str


class SearchService:
    """
    全文検索とファイル名検索をまとめて提供する。
    ユーザー入力は FTS5 構文としてではなく、通常の検索語として安全に扱う。
    """

    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()
        self.index_service = IndexService(connection=self.connection)

    def search(self, params: SearchQueryParams) -> SearchResponse:
        normalized_target_path = normalize_path_str(params.full_path)
        excluded_keywords = self.index_service._parse_exclude_keywords(params.exclude_keywords)
        self.index_service.ensure_fresh_target(
            full_path=normalized_target_path,
            refresh_window_minutes=params.refresh_window_minutes,
            exclude_keywords=params.exclude_keywords,
            index_depth=params.index_depth,
            types=params.types,
        )

        if params.regex_enabled:
            return self._search_with_regex(
                params=params,
                normalized_target_path=normalized_target_path,
                excluded_keywords=excluded_keywords,
            )

        return self._search_with_fts(
            params=params,
            normalized_target_path=normalized_target_path,
            excluded_keywords=excluded_keywords,
        )

    def _search_with_fts(
        self,
        *,
        params: SearchQueryParams,
        normalized_target_path: str,
        excluded_keywords: list[str],
    ) -> SearchResponse:
        """
        通常モードでは既存の FTS5 ベース全文検索を利用する。
        CTE を1回だけ評価し、COUNT と結果を同時に取得する。
        """
        where_clause, values = self._build_common_filters(
            normalized_target_path=normalized_target_path,
            index_depth=params.index_depth,
            types=params.types,
        )

        normalized_query = params.q.strip()
        escaped_query = self._escape_like_pattern(normalized_query.lower())
        body_fts_query = self._build_fts_match_query(normalized_query)
        cjk_bigram_query = build_cjk_bigram_match_query(normalized_query)

        matched_queries = [
            f"""
                SELECT
                    files.id AS file_id,
                    0 AS match_rank,
                    bm25(file_segments_fts) AS score,
                    snippet(file_segments_fts, 0, '<mark>', '</mark>', ' ... ', 36) AS snippet,
                    file_segments.segment_type AS segment_type,
                    NULL AS body_content
                FROM file_segments_fts
                JOIN file_segments ON file_segments.id = file_segments_fts.rowid
                JOIN files ON files.id = file_segments.file_id
                WHERE {where_clause}
                  AND file_segments.segment_type = 'body'
                  AND file_segments_fts MATCH ?
            """,
        ]
        query_values: list[object] = [*values, body_fts_query]

        if cjk_bigram_query is not None:
            matched_queries.append(
                f"""
                SELECT
                    files.id AS file_id,
                    1 AS match_rank,
                    bm25(file_segments_fts) AS score,
                    NULL AS snippet,
                    file_segments.segment_type AS segment_type,
                    body_segments.content AS body_content
                FROM file_segments_fts
                JOIN file_segments ON file_segments.id = file_segments_fts.rowid
                JOIN files ON files.id = file_segments.file_id
                JOIN file_segments AS body_segments
                  ON body_segments.file_id = files.id
                 AND body_segments.segment_type = 'body'
                WHERE {where_clause}
                  AND file_segments.segment_type = 'cjk_bigram'
                  AND file_segments_fts MATCH ?
                """
            )
            query_values.extend([*values, cjk_bigram_query])

        matched_queries.append(
            f"""
                SELECT
                    files.id AS file_id,
                    2 AS match_rank,
                    1000000.0 AS score,
                    NULL AS snippet,
                    'filename' AS segment_type,
                    NULL AS body_content
                FROM files
                WHERE {where_clause} AND lower(files.file_name) LIKE ? ESCAPE '\\'
            """
        )
        query_values.extend([*values, f"%{escaped_query}%"])
        query_values.extend([params.limit, params.offset])

        rows = self.connection.execute(
            f"""
            WITH matched_files AS (
                {" UNION ALL ".join(matched_queries)}
            ),
            ranked_matches AS (
                SELECT
                    file_id,
                    match_rank,
                    score,
                    snippet,
                    segment_type,
                    body_content,
                    ROW_NUMBER() OVER (PARTITION BY file_id ORDER BY match_rank, score, file_id) AS rn
                FROM matched_files
            ),
            filtered AS (
                SELECT * FROM ranked_matches WHERE rn = 1
            ),
            total_count AS (
                SELECT COUNT(*) AS total
                FROM filtered
            ),
            paged_matches AS (
                SELECT
                    files.id AS file_id,
                    files.file_name,
                    files.normalized_path,
                    files.file_ext,
                    files.mtime,
                    filtered.snippet,
                    filtered.segment_type,
                    filtered.body_content,
                    filtered.match_rank,
                    filtered.score
                FROM filtered
                JOIN files ON files.id = filtered.file_id
                ORDER BY filtered.match_rank, filtered.score, files.mtime DESC
                LIMIT ? OFFSET ?
            )
            SELECT
                paged_matches.file_id,
                paged_matches.file_name,
                paged_matches.normalized_path,
                paged_matches.file_ext,
                paged_matches.mtime,
                paged_matches.snippet,
                paged_matches.segment_type,
                paged_matches.body_content,
                total_count.total
            FROM total_count
            LEFT JOIN paged_matches ON 1 = 1
            ORDER BY paged_matches.match_rank, paged_matches.score, paged_matches.mtime DESC
            """,
            tuple(query_values),
        ).fetchall()

        total = int(rows[0]["total"]) if rows else 0
        items = [
            SearchResultItem(
                file_id=int(row["file_id"]),
                target_path=normalized_target_path,
                file_name=str(row["file_name"]),
                full_path=str(row["normalized_path"]),
                file_ext=str(row["file_ext"]),
                mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                snippet=self._resolve_snippet(
                    snippet=row["snippet"],
                    file_name=str(row["file_name"]),
                    segment_type=str(row["segment_type"] or "filename"),
                    body_content=row["body_content"],
                    query=normalized_query,
                ),
            )
            for row in rows
            if row["file_id"] is not None
            and not self.index_service._should_exclude_path(normalize_path(str(row["normalized_path"])), excluded_keywords)
        ]
        return SearchResponse(total=total, items=items)

    def _search_with_regex(
        self,
        *,
        params: SearchQueryParams,
        normalized_target_path: str,
        excluded_keywords: list[str],
    ) -> SearchResponse:
        """
        正規表現モードでは Python の re で本文とファイル名を評価する。
        イテレータで逐次処理し、メモリ使用量を抑える。
        """
        where_clause, values = self._build_common_filters(
            normalized_target_path=normalized_target_path,
            index_depth=params.index_depth,
            types=params.types,
        )
        pattern = self._compile_regex(params.q)
        cursor = self.connection.execute(
            f"""
            SELECT
                files.id AS file_id,
                files.file_name,
                files.normalized_path,
                files.file_ext,
                files.mtime,
                file_segments.content
            FROM files
            LEFT JOIN file_segments
                ON file_segments.file_id = files.id
               AND file_segments.segment_type = 'body'
            WHERE {where_clause}
            ORDER BY files.mtime DESC, files.id DESC
            """,
            tuple(values),
        )

        items: list[SearchResultItem] = []
        matched_count = 0
        for row in cursor:
            normalized_path = str(row["normalized_path"])
            if self.index_service._should_exclude_path(normalize_path(normalized_path), excluded_keywords):
                continue

            file_name = str(row["file_name"])
            content = str(row["content"] or "")
            content_match = pattern.search(content)
            file_name_match = pattern.search(file_name)
            if content_match is None and file_name_match is None:
                continue

            matched_count += 1
            # offset 範囲外はスキップ
            if matched_count <= params.offset:
                continue
            # limit に達したらカウントのみ続行
            if len(items) >= params.limit:
                continue

            items.append(
                SearchResultItem(
                    file_id=int(row["file_id"]),
                    target_path=normalized_target_path,
                    file_name=file_name,
                    full_path=normalized_path,
                    file_ext=str(row["file_ext"]),
                    mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                    snippet=self._build_regex_snippet(
                        content=content,
                        file_name=file_name,
                        content_match=content_match,
                        file_name_match=file_name_match,
                    ),
                )
            )

        return SearchResponse(total=matched_count, items=items)

    def _resolve_snippet(
        self,
        *,
        snippet: object,
        file_name: str,
        segment_type: str = "filename",
        body_content: object = None,
        query: str = "",
    ) -> str:
        if segment_type == "cjk_bigram":
            literal_snippet = self._build_literal_snippet(content=str(body_content or ""), query=query)
            if literal_snippet is not None:
                return literal_snippet
        if isinstance(snippet, str) and snippet.strip():
            return snippet
        escaped_name = escape(file_name)
        return (
            f"ファイル名一致: <mark>{escaped_name}</mark>。"
            " 本文中には検索語の直接一致が見つからなかったため、"
            "ファイル名ベースの候補として表示しています。"
        )

    def _build_literal_snippet(self, *, content: str, query: str) -> str | None:
        """
        補助インデックス由来のヒットでは、元本文から素直な部分一致抜粋を組み立てる。
        """
        if not content or not query.strip():
            return None

        match_range: tuple[int, int] | None = None
        lowered_content = content.lower()
        for term in (item for item in query.split() if item):
            start = lowered_content.find(term.lower())
            if start < 0:
                continue
            candidate = (start, start + len(term))
            if match_range is None or candidate[0] < match_range[0]:
                match_range = candidate

        if match_range is None:
            return None

        start, end = match_range
        snippet_start = max(start - 48, 0)
        snippet_end = min(end + 48, len(content))
        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(content) else ""
        before = escape(content[snippet_start:start])
        matched = escape(content[start:end])
        after = escape(content[end:snippet_end])
        return f"{prefix}{before}<mark>{matched}</mark>{after}{suffix}"

    def _escape_like_pattern(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _build_fts_match_query(self, value: str) -> str:
        """
        FTS5 の構文文字を無害化しつつ、空白区切りは AND 検索として扱う。
        """
        terms = [term for term in value.split() if term]
        if not terms:
            return '""'
        return " AND ".join(self._quote_fts_term(term) for term in terms)

    def _quote_fts_term(self, term: str) -> str:
        escaped_term = term.replace('"', '""')
        return f'"{escaped_term}"'

    def _build_common_filters(
        self,
        *,
        normalized_target_path: str,
        index_depth: int,
        types: str | None,
    ) -> tuple[str, list[object]]:
        """
        検索モード共通のパス・階層・拡張子フィルタを組み立てる。
        """
        prefix_start, prefix_end = get_descendant_path_range(normalized_target_path)
        descendant_prefix = get_descendant_path_prefix(normalized_target_path)
        depth_expression = (
            "(length(files.normalized_path) - length(replace(files.normalized_path, '/', '')))"
            " - (length(?) - length(replace(?, '/', '')))"
        )
        filters: list[str] = ["files.normalized_path >= ?", "files.normalized_path < ?", f"{depth_expression} <= ?"]
        values: list[object] = [prefix_start, prefix_end, descendant_prefix, descendant_prefix, index_depth]

        if types:
            extensions = [item.strip().lower() for item in types.split(",") if item.strip()]
            if extensions:
                placeholders = ", ".join("?" for _ in extensions)
                filters.append(f"files.file_ext IN ({placeholders})")
                values.extend(extensions)

        return " AND ".join(filters), values

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
        content_match: re.Match[str] | None,
        file_name_match: re.Match[str] | None,
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

        escaped_name = escape(file_name)
        if file_name_match is None:
            return self._resolve_snippet(snippet=None, file_name=file_name)

        start = file_name_match.start()
        end = file_name_match.end()
        return (
            "ファイル名一致: "
            f"{escape(file_name[:start])}<mark>{escape(file_name[start:end])}</mark>{escape(file_name[end:])}"
        )
