from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from fastapi import HTTPException, status

from app.db.connection import get_connection
from app.extractors.text_extractor import extract_text, supports_extension
from app.models.indexing import IndexStatusResponse
from app.services.path_service import normalize_path


class IndexService:
    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()

    def ensure_fresh_target(
        self,
        *,
        full_path: str,
        refresh_window_minutes: int,
        exclude_keywords: str | None = None,
    ) -> None:
        if self._is_running():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Indexing is already running.")

        started_at = datetime.now(UTC).isoformat()
        self._update_status(is_running=True, last_started_at=started_at, last_error=None)

        total_files = 0
        error_count = 0
        try:
            normalized_keywords = self._normalize_exclude_keywords(exclude_keywords)
            target = self._ensure_target(full_path=full_path, exclude_keywords=normalized_keywords)
            if self._needs_refresh(target, refresh_window_minutes, normalized_keywords):
                stats = self._index_target(target, normalized_keywords)
                total_files = stats["file_count"]
                error_count = stats["error_count"]
                self._mark_target_indexed(int(target["id"]), normalized_keywords)
            else:
                total_files = self._count_target_files(str(target["full_path"]))
        except Exception as error:
            self._update_status(
                is_running=False,
                last_finished_at=datetime.now(UTC).isoformat(),
                last_error=str(error),
                total_files=total_files,
                error_count=error_count + 1,
            )
            raise

        self._update_status(
            is_running=False,
            last_finished_at=datetime.now(UTC).isoformat(),
            total_files=total_files,
            error_count=error_count,
            last_error=None,
        )

    def get_status(self) -> IndexStatusResponse:
        row = self.connection.execute(
            """
            SELECT last_started_at, last_finished_at, total_files, error_count, is_running, last_error
            FROM index_runs
            WHERE id = 1
            """
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Index status unavailable.")
        return IndexStatusResponse.model_validate(dict(row))

    def _is_running(self) -> bool:
        row = self.connection.execute("SELECT is_running FROM index_runs WHERE id = 1").fetchone()
        return bool(row["is_running"]) if row else False

    def _ensure_target(self, *, full_path: str, exclude_keywords: str) -> dict[str, object]:
        normalized_path = normalize_path(full_path)
        if not normalized_path.exists() or not normalized_path.is_dir():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder path must be an existing directory.")

        row = self.connection.execute(
            """
            SELECT id, full_path, last_indexed_at, exclude_keywords, created_at, updated_at
            FROM targets
            WHERE full_path = ?
            """,
            (normalized_path.as_posix(),),
        ).fetchone()
        if row is not None:
            return dict(row)

        now = datetime.now(UTC).isoformat()
        cursor = self.connection.execute(
            """
            INSERT INTO targets(full_path, last_indexed_at, exclude_keywords, created_at, updated_at)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (normalized_path.as_posix(), exclude_keywords, now, now),
        )
        self.connection.commit()
        created = self.connection.execute(
            """
            SELECT id, full_path, last_indexed_at, exclude_keywords, created_at, updated_at
            FROM targets
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return dict(created)

    def _needs_refresh(self, target: dict[str, object], refresh_window_minutes: int, exclude_keywords: str) -> bool:
        last_indexed_at = target["last_indexed_at"]
        if last_indexed_at is None:
            return True
        if str(target.get("exclude_keywords") or "") != exclude_keywords:
            return True
        indexed_at = datetime.fromisoformat(str(last_indexed_at))
        elapsed_seconds = (datetime.now(UTC) - indexed_at).total_seconds()
        return elapsed_seconds > refresh_window_minutes * 60

    def _index_target(self, target: dict[str, object], exclude_keywords: str) -> dict[str, object]:
        folder_path = normalize_path(str(target["full_path"]))
        normalized_paths: set[str] = set()
        file_count = 0
        error_count = 0
        keywords = self._parse_exclude_keywords(exclude_keywords)

        for path in folder_path.rglob("*"):
            if self._should_exclude_path(path, keywords):
                continue
            if not path.is_file() or not supports_extension(path):
                continue
            normalized_path = path.resolve().as_posix()
            normalized_paths.add(normalized_path)
            try:
                self._upsert_file(path=path)
                file_count += 1
            except Exception as error:
                error_count += 1
                self._record_file_error(path, error)

        self._remove_deleted_files(normalized_paths, root_path=folder_path.as_posix())
        return {"file_count": file_count, "error_count": error_count}

    def _upsert_file(self, *, path: Path) -> None:
        stat = path.stat()
        normalized_path = path.resolve().as_posix()
        existing = self.connection.execute(
            "SELECT id, mtime, size FROM files WHERE normalized_path = ?",
            (normalized_path,),
        ).fetchone()

        if existing and float(existing["mtime"]) == stat.st_mtime and int(existing["size"]) == stat.st_size:
            return

        content = extract_text(path)
        indexed_at = datetime.now(UTC).isoformat()

        if existing:
            file_id = int(existing["id"])
            self.connection.execute(
                """
                UPDATE files
                SET full_path = ?, file_name = ?, file_ext = ?,
                    mtime = ?, size = ?, indexed_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    normalized_path,
                    path.name,
                    path.suffix.lower(),
                    stat.st_mtime,
                    stat.st_size,
                    indexed_at,
                    file_id,
                ),
            )
            self.connection.execute("DELETE FROM file_segments WHERE file_id = ?", (file_id,))
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO files(
                    full_path, normalized_path,
                    file_name, file_ext, mtime, size, indexed_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    normalized_path,
                    normalized_path,
                    path.name,
                    path.suffix.lower(),
                    stat.st_mtime,
                    stat.st_size,
                    indexed_at,
                ),
            )
            file_id = int(cursor.lastrowid)

        self.connection.execute(
            """
            INSERT INTO file_segments(file_id, segment_type, segment_label, content)
            VALUES (?, ?, ?, ?)
            """,
            (file_id, "body", normalized_path, content),
        )
        self.connection.commit()

    def _record_file_error(self, path: Path, error: Exception) -> None:
        normalized_path = path.resolve().as_posix()
        row = self.connection.execute(
            "SELECT id FROM files WHERE normalized_path = ?",
            (normalized_path,),
        ).fetchone()
        if row is None:
            return
        self.connection.execute(
            "UPDATE files SET last_error = ? WHERE id = ?",
            (str(error), int(row["id"])),
        )
        self.connection.commit()

    def _remove_deleted_files(self, normalized_paths: set[str], *, root_path: str) -> None:
        prefix = f"{root_path}/%"
        rows = self.connection.execute(
            "SELECT id, normalized_path FROM files WHERE normalized_path LIKE ?",
            (prefix,),
        ).fetchall()
        deleted_ids = [int(row["id"]) for row in rows if row["normalized_path"] not in normalized_paths]
        if not deleted_ids:
            return
        self.connection.executemany("DELETE FROM files WHERE id = ?", [(file_id,) for file_id in deleted_ids])
        self.connection.commit()

    def _mark_target_indexed(self, target_id: int, exclude_keywords: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            "UPDATE targets SET last_indexed_at = ?, exclude_keywords = ?, updated_at = ? WHERE id = ?",
            (now, exclude_keywords, now, target_id),
        )
        self.connection.commit()

    def _count_target_files(self, root_path: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM files WHERE normalized_path LIKE ?",
            (f"{root_path}/%",),
        ).fetchone()
        return int(row["count"])

    def _update_status(
        self,
        *,
        is_running: bool,
        last_started_at: str | None = None,
        last_finished_at: str | None = None,
        last_error: str | None = None,
        total_files: int | None = None,
        error_count: int | None = None,
    ) -> None:
        current = self.connection.execute("SELECT * FROM index_runs WHERE id = 1").fetchone()
        self.connection.execute(
            """
            UPDATE index_runs
            SET is_running = ?,
                last_started_at = COALESCE(?, last_started_at),
                last_finished_at = COALESCE(?, last_finished_at),
                last_error = ?,
                total_files = COALESCE(?, total_files),
                error_count = COALESCE(?, error_count)
            WHERE id = 1
            """,
            (
                int(is_running),
                last_started_at,
                last_finished_at,
                last_error,
                total_files if total_files is not None else current["total_files"],
                error_count if error_count is not None else current["error_count"],
            ),
        )
        self.connection.commit()

    def _normalize_exclude_keywords(self, value: str | None) -> str:
        return "\n".join(self._parse_exclude_keywords(value))

    def _parse_exclude_keywords(self, value: str | None) -> list[str]:
        seen: set[str] = set()
        keywords: list[str] = []
        for line in (value or "").splitlines():
            keyword = line.strip().lower()
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            keywords.append(keyword)
        return keywords

    def _should_exclude_path(self, path: Path, keywords: list[str]) -> bool:
        if not keywords:
            return False
        return any(self._part_matches_keyword(part.lower(), keywords) for part in path.parts)

    def _part_matches_keyword(self, part: str, keywords: list[str]) -> bool:
        ascii_tokens = [token for token in self._split_ascii_tokens(part) if token]
        stripped_part = part.lstrip(".")
        for keyword in keywords:
            if keyword == part or keyword == stripped_part:
                return True
            if any(ord(char) > 127 for char in keyword) and keyword in part:
                return True
            if keyword in ascii_tokens:
                return True
        return False

    def _split_ascii_tokens(self, value: str) -> list[str]:
        token: list[str] = []
        tokens: list[str] = []
        for char in value:
            if char.isascii() and char.isalnum():
                token.append(char)
                continue
            if token:
                tokens.append("".join(token))
                token.clear()
        if token:
            tokens.append("".join(token))
        return tokens
