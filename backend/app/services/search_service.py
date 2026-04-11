from datetime import UTC, datetime
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
            index_depth=params.index_depth,
            refresh_window_minutes=params.refresh_window_minutes,
        )

        filters: list[str] = ["file_segments_fts MATCH ?", "targets.full_path = ?", "targets.index_depth = ?"]
        values: list[object] = [params.q, normalized_target_path, params.index_depth]

        if params.types:
            extensions = [item.strip().lower() for item in params.types.split(",") if item.strip()]
            if extensions:
                placeholders = ", ".join("?" for _ in extensions)
                filters.append(f"files.file_ext IN ({placeholders})")
                values.extend(extensions)

        where_clause = " AND ".join(filters)
        total = self.connection.execute(
            f"""
            SELECT COUNT(DISTINCT files.id) AS total
            FROM file_segments_fts
            JOIN file_segments ON file_segments.id = file_segments_fts.rowid
            JOIN files ON files.id = file_segments.file_id
            JOIN targets ON targets.id = files.target_id
            WHERE {where_clause}
            """,
            tuple(values),
        ).fetchone()["total"]

        query_values = [*values, params.limit, params.offset]
        rows = self.connection.execute(
            f"""
            SELECT DISTINCT
                files.id AS file_id,
                targets.id AS target_id,
                targets.full_path AS target_path,
                files.file_name,
                files.normalized_path,
                files.file_ext,
                files.mtime,
                snippet(file_segments_fts, 0, '<mark>', '</mark>', ' ... ', 16) AS snippet
            FROM file_segments_fts
            JOIN file_segments ON file_segments.id = file_segments_fts.rowid
            JOIN files ON files.id = file_segments.file_id
            JOIN targets ON targets.id = files.target_id
            WHERE {where_clause}
            ORDER BY bm25(file_segments_fts), files.mtime DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_values),
        ).fetchall()

        items = [
            SearchResultItem(
                file_id=int(row["file_id"]),
                target_id=int(row["target_id"]),
                target_path=str(row["target_path"]),
                file_name=str(row["file_name"]),
                full_path=str(row["normalized_path"]),
                file_ext=str(row["file_ext"]),
                mtime=datetime.fromtimestamp(float(row["mtime"]), tz=UTC),
                snippet=str(row["snippet"]),
            )
            for row in rows
        ]
        return SearchResponse(total=int(total), items=items)
