from datetime import UTC, datetime
from html import escape
from sqlite3 import Connection

from app.db.connection import get_connection
from app.models.search import SearchQueryParams, SearchResponse, SearchResultItem
from app.services.index_service import IndexService
from app.services.path_service import normalize_path_str


class SearchService:
    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()
        self.index_service = IndexService(connection=self.connection)

    def search(self, params: SearchQueryParams) -> SearchResponse:
        normalized_target_path = normalize_path_str(params.full_path)
        self.index_service.ensure_fresh_target(
            full_path=normalized_target_path,
            refresh_window_minutes=params.refresh_window_minutes,
        )

        path_prefix = f"{normalized_target_path}/%"
        depth_expression = (
            "(length(files.normalized_path) - length(replace(files.normalized_path, '/', '')))"
            " - (length(?) - length(replace(?, '/', ''))) - 1"
        )
        filters: list[str] = ["files.normalized_path LIKE ?", f"{depth_expression} <= ?"]
        values: list[object] = [path_prefix, normalized_target_path, normalized_target_path, params.index_depth]

        if params.types:
            extensions = [item.strip().lower() for item in params.types.split(",") if item.strip()]
            if extensions:
                placeholders = ", ".join("?" for _ in extensions)
                filters.append(f"files.file_ext IN ({placeholders})")
                values.extend(extensions)

        where_clause = " AND ".join(filters)
        escaped_query = self._escape_like_pattern(params.q.strip().lower())
        common_search_sql = f"""
            WITH matched_files AS (
                SELECT
                    files.id AS file_id,
                    0 AS match_rank,
                    bm25(file_segments_fts) AS score,
                    snippet(file_segments_fts, 0, '<mark>', '</mark>', ' ... ', 36) AS snippet
                FROM file_segments_fts
                JOIN file_segments ON file_segments.id = file_segments_fts.rowid
                JOIN files ON files.id = file_segments.file_id
                WHERE {where_clause} AND file_segments_fts MATCH ?

                UNION ALL

                SELECT
                    files.id AS file_id,
                    1 AS match_rank,
                    1000000.0 AS score,
                    NULL AS snippet
                FROM files
                WHERE {where_clause} AND lower(files.file_name) LIKE ? ESCAPE '\\'
            ),
            ranked_matches AS (
                SELECT
                    file_id,
                    match_rank,
                    score,
                    snippet,
                    ROW_NUMBER() OVER (PARTITION BY file_id ORDER BY match_rank, score, file_id) AS rn
                FROM matched_files
            )
        """
        match_values = [*values, params.q, *values, f"%{escaped_query}%"]
        total = self.connection.execute(
            f"""
            {common_search_sql}
            SELECT COUNT(*) AS total
            FROM ranked_matches
            WHERE rn = 1
            """,
            tuple(match_values),
        ).fetchone()["total"]

        query_values = [*match_values, params.limit, params.offset]
        rows = self.connection.execute(
            f"""
            {common_search_sql}
            SELECT
                files.id AS file_id,
                files.file_name,
                files.normalized_path,
                files.file_ext,
                files.mtime,
                ranked_matches.snippet
            FROM ranked_matches
            JOIN files ON files.id = ranked_matches.file_id
            WHERE ranked_matches.rn = 1
            ORDER BY ranked_matches.match_rank, ranked_matches.score, files.mtime DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_values),
        ).fetchall()

        items = [
            SearchResultItem(
                file_id=int(row["file_id"]),
                target_path=normalized_target_path,
                file_name=str(row["file_name"]),
                full_path=str(row["normalized_path"]),
                file_ext=str(row["file_ext"]),
                mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                snippet=self._resolve_snippet(snippet=row["snippet"], file_name=str(row["file_name"])),
            )
            for row in rows
        ]
        return SearchResponse(total=int(total), items=items)

    def _resolve_snippet(self, *, snippet: object, file_name: str) -> str:
        if isinstance(snippet, str) and snippet.strip():
            return snippet
        escaped_name = escape(file_name)
        return (
            f"ファイル名一致: <mark>{escaped_name}</mark>。"
            " 本文中には検索語の直接一致が見つからなかったため、"
            "ファイル名ベースの候補として表示しています。"
        )

    def _escape_like_pattern(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
