import os
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
        """指定ターゲットの全ファイルをインデックスする。os.scandirでディレクトリ除外を早期に行い、バッチcommitで効率化。"""
        folder_path = normalize_path(str(target["full_path"]))
        normalized_paths: set[str] = set()
        file_count = 0
        error_count = 0
        keywords = self._parse_exclude_keywords(exclude_keywords)
        keyword_set = frozenset(keywords)
        non_ascii_keywords = [kw for kw in keywords if any(ord(c) > 127 for c in kw)]
        batch_size = 100

        for path in self._walk_files(folder_path, keyword_set, non_ascii_keywords):
            normalized_path = path.resolve().as_posix()
            normalized_paths.add(normalized_path)
            try:
                self._upsert_file(path=path)
                file_count += 1
                if file_count % batch_size == 0:
                    self.connection.commit()
            except Exception as error:
                error_count += 1
                self._record_file_error(path, error)

        self.connection.commit()
        self._remove_deleted_files(normalized_paths, root_path=folder_path.as_posix())
        return {"file_count": file_count, "error_count": error_count}

    def _walk_files(
        self,
        root: Path,
        keyword_set: frozenset[str],
        non_ascii_keywords: list[str],
    ):
        """
        os.scandir ベースの高速ファイル走査。
        除外キーワードに一致するディレクトリは再帰しないため、rglob より高速。
        """
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        if not self._should_exclude_path_with_keywords(path, keyword_set, non_ascii_keywords):
                            yield from self._walk_files(path, keyword_set, non_ascii_keywords)
                    elif entry.is_file(follow_symlinks=False):
                        if supports_extension(path) and not self._should_exclude_path_with_keywords(
                            path,
                            keyword_set,
                            non_ascii_keywords,
                        ):
                            yield path
        except PermissionError:
            pass

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

    def _remove_deleted_files(self, normalized_paths: set[str], *, root_path: str) -> None:
        """DB上に存在するが実ファイルが無くなったレコードをバッチ削除する。"""
        prefix = f"{root_path}/%"
        rows = self.connection.execute(
            "SELECT id, normalized_path FROM files WHERE normalized_path LIKE ?",
            (prefix,),
        ).fetchall()
        deleted_ids = [int(row["id"]) for row in rows if row["normalized_path"] not in normalized_paths]
        if not deleted_ids:
            return
        # IN句でバッチ削除（executemanyより効率的）
        chunk_size = 500
        for i in range(0, len(deleted_ids), chunk_size):
            chunk = deleted_ids[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            self.connection.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)
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
        """インデックス実行ステータスを更新する。不要なSELECTを省き、COALESCEで処理。"""
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
                total_files,
                error_count,
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
        """パスの各パートが除外キーワードに一致するか判定する。検索サービスからも利用される。"""
        if not keywords:
            return False
        keyword_set = frozenset(keywords)
        non_ascii_keywords = [kw for kw in keywords if any(ord(c) > 127 for c in kw)]
        return self._should_exclude_path_with_keywords(path, keyword_set, non_ascii_keywords)

    def _should_exclude_path_with_keywords(
        self,
        path: Path,
        keyword_set: frozenset[str],
        non_ascii_keywords: list[str],
    ) -> bool:
        """事前計算済みキーワード集合を用いてパス全体の除外判定を行う。"""
        return any(self._is_excluded_name(part, keyword_set, non_ascii_keywords) for part in path.parts)

    def _is_excluded_name(self, name: str, keyword_set: frozenset[str], non_ascii_keywords: list[str]) -> bool:
        """
        ディレクトリ名/ファイル名が除外キーワードに一致するか判定する。
        keyword_set による O(1) ルックアップで高速化。
        """
        lower_name = name.lower()
        stripped_name = lower_name.lstrip(".")
        # 完全一致（set O(1)）
        if lower_name in keyword_set or stripped_name in keyword_set:
            return True
        # 非ASCIIキーワードのサブストリング検索
        for kw in non_ascii_keywords:
            if kw in lower_name:
                return True
        # ASCIIトークン分割によるマッチ
        tokens = set(self._split_ascii_tokens(lower_name))
        if tokens & keyword_set:
            return True
        return False

    def _split_ascii_tokens(self, value: str) -> list[str]:
        """文字列からASCII英数字トークンを分割する。"""
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
