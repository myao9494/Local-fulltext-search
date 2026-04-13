"""
インデックス更新サービス。
走査範囲を index_depth と対象拡張子で絞り込み、本文抽出だけを並列化して SQLite 書き込みは直列で行う。

高速化:
- os.scandir の再帰走査でエントリ名のみ除外チェック（親パーツの冗長なチェックを省略）
- I/Oバウンド対応でワーカー数上限を引き上げ
- _clear_failed_file の個別呼び出しを廃止し一括処理に統合
- 既存ファイル検索を LIKE から範囲クエリに変更しインデックス活用
- CASCADE 削除時に FTS5 トリガーを確実に発火させるための明示的 DELETE
"""

from __future__ import annotations

import os
from concurrent.futures import ALL_COMPLETED, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from fastapi import HTTPException, status

from app.db.connection import get_connection
from app.extractors.text_extractor import extract_text, normalize_extension_filter, supports_content_extraction
from app.models.indexing import FailedFileItem, FailedFileListResponse, IndexStatusResponse
from app.services.path_service import get_descendant_path_prefix, get_descendant_path_range, normalize_path


@dataclass(frozen=True)
class IndexedFileCandidate:
    """
    インデックス対象ファイルの事前計算済みメタデータを保持する。
    """

    path: Path
    normalized_path: str
    mtime: float
    size: int
    existing_id: int | None


class IndexService:
    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()

    def ensure_fresh_target(
        self,
        *,
        full_path: str,
        refresh_window_minutes: int,
        exclude_keywords: str | None = None,
        index_depth: int = 5,
        types: str | None = None,
    ) -> None:
        if self._is_running():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Indexing is already running.")

        started_at = datetime.now(UTC).isoformat()
        self._update_status(is_running=True, last_started_at=started_at, last_error=None)

        normalized_keywords = self._normalize_exclude_keywords(exclude_keywords)
        normalized_extensions = self._normalize_selected_extensions(types)

        total_files = 0
        error_count = 0
        try:
            target = self._ensure_target(
                full_path=full_path,
                exclude_keywords=normalized_keywords,
                index_depth=index_depth,
                selected_extensions=normalized_extensions,
            )
            if self._needs_refresh(target, refresh_window_minutes, normalized_keywords, index_depth, normalized_extensions):
                stats = self._index_target(
                    target,
                    normalized_keywords,
                    index_depth=index_depth,
                    selected_extensions=normalized_extensions,
                )
                total_files = stats["file_count"]
                error_count = stats["error_count"]
                self._mark_target_indexed(
                    int(target["id"]),
                    exclude_keywords=normalized_keywords,
                    index_depth=index_depth,
                    selected_extensions=normalized_extensions,
                )
            else:
                total_files = self._count_target_files(
                    str(target["full_path"]),
                    index_depth=int(target["index_depth"]),
                    selected_extensions=str(target["selected_extensions"]),
                )
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

    def get_failed_files(self) -> FailedFileListResponse:
        """
        直近のインデックス処理で取得に失敗したファイル一覧を返す。
        """
        rows = self.connection.execute(
            """
            SELECT normalized_path, file_name, error_message, last_failed_at
            FROM failed_files
            ORDER BY last_failed_at DESC, normalized_path ASC
            """
        ).fetchall()
        return FailedFileListResponse(items=[FailedFileItem.model_validate(dict(row)) for row in rows])

    def _is_running(self) -> bool:
        row = self.connection.execute("SELECT is_running FROM index_runs WHERE id = 1").fetchone()
        return bool(row["is_running"]) if row else False

    def _ensure_target(
        self,
        *,
        full_path: str,
        exclude_keywords: str,
        index_depth: int,
        selected_extensions: str,
    ) -> dict[str, object]:
        normalized_path = normalize_path(full_path)
        if not normalized_path.exists() or not normalized_path.is_dir():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder path must be an existing directory.")

        row = self.connection.execute(
            """
            SELECT
                id, full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions, created_at, updated_at
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
            INSERT INTO targets(
                full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions, created_at, updated_at
            )
            VALUES (?, NULL, ?, ?, ?, ?, ?)
            """,
            (normalized_path.as_posix(), exclude_keywords, index_depth, selected_extensions, now, now),
        )
        self.connection.commit()
        created = self.connection.execute(
            """
            SELECT
                id, full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions, created_at, updated_at
            FROM targets
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return dict(created)

    def _needs_refresh(
        self,
        target: dict[str, object],
        refresh_window_minutes: int,
        exclude_keywords: str,
        index_depth: int,
        selected_extensions: str,
    ) -> bool:
        last_indexed_at = target["last_indexed_at"]
        if last_indexed_at is None:
            return True
        if str(target.get("exclude_keywords") or "") != exclude_keywords:
            return True
        if int(target.get("index_depth") or 0) != index_depth:
            return True
        if str(target.get("selected_extensions") or "") != selected_extensions:
            return True
        indexed_at = datetime.fromisoformat(str(last_indexed_at))
        elapsed_seconds = (datetime.now(UTC) - indexed_at).total_seconds()
        return elapsed_seconds > refresh_window_minutes * 60

    def _index_target(
        self,
        target: dict[str, object],
        exclude_keywords: str,
        *,
        index_depth: int,
        selected_extensions: str,
    ) -> dict[str, object]:
        """
        指定ターゲット配下を高速に再走査する。
        走査は os.scandir、本文抽出はスレッド並列、DB 書き込みは直列でまとめる。
        """
        folder_path = normalize_path(str(target["full_path"]))
        normalized_paths: set[str] = set()
        failed_paths: set[str] = set()
        file_count = 0
        error_count = 0
        write_count = 0

        keywords = self._parse_exclude_keywords(exclude_keywords)
        keyword_set = frozenset(keywords)
        non_ascii_keywords = [kw for kw in keywords if any(ord(c) > 127 for c in kw)]
        allowed_extensions = normalize_extension_filter(selected_extensions)
        existing_files = self._load_existing_files(folder_path.as_posix())
        batch_size = 100
        max_workers = self._resolve_extract_worker_count()
        max_pending = max_workers * 4
        pending: dict[Future[str], IndexedFileCandidate] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for path in self._walk_files(
                folder_path,
                keyword_set,
                non_ascii_keywords,
                allowed_extensions=allowed_extensions,
                max_depth=index_depth,
            ):
                stat = path.stat()
                normalized_path = path.resolve().as_posix()
                normalized_paths.add(normalized_path)
                existing = existing_files.get(normalized_path)

                if self._can_skip_existing_file(existing, stat):
                    file_count += 1
                    continue

                candidate = IndexedFileCandidate(
                    path=path,
                    normalized_path=normalized_path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    existing_id=int(existing["id"]) if existing is not None else None,
                )

                if supports_content_extraction(path):
                    pending[executor.submit(extract_text, path)] = candidate
                    if len(pending) >= max_pending:
                        result = self._drain_pending_futures(pending, failed_paths, drain_all=False)
                        file_count += result["file_count"]
                        error_count += result["error_count"]
                        write_count += result["write_count"]
                else:
                    self._upsert_file(candidate=candidate, content=None)
                    file_count += 1
                    write_count += 1
                    if write_count % batch_size == 0:
                        self.connection.commit()

            result = self._drain_pending_futures(pending, failed_paths, drain_all=True)
            file_count += result["file_count"]
            error_count += result["error_count"]
            write_count += result["write_count"]

        self.connection.commit()
        self._remove_deleted_files(normalized_paths, root_path=folder_path.as_posix())
        self._clear_resolved_failed_files(root_path=folder_path.as_posix(), failed_paths=failed_paths)
        return {"file_count": file_count, "error_count": error_count}

    def _resolve_extract_worker_count(self) -> int:
        """
        本文抽出スレッド数を CPU 数に応じて上限付きで決める。
        I/Oバウンドタスクが支配的なため、CPU数の2倍（上限16）を使用する。
        """
        cpu_count = os.cpu_count() or 4
        return max(2, min(16, cpu_count * 2))

    def _drain_pending_futures(
        self,
        pending: dict[Future[str], IndexedFileCandidate],
        failed_paths: set[str],
        *,
        drain_all: bool,
    ) -> dict[str, int]:
        """
        完了した抽出タスクだけを取り出して DB へ反映する。
        """
        if not pending:
            return {"file_count": 0, "error_count": 0, "write_count": 0}

        done, _ = wait(
            pending.keys(),
            return_when=FIRST_COMPLETED if not drain_all else ALL_COMPLETED,
        )

        file_count = 0
        error_count = 0
        write_count = 0
        for future in done:
            candidate = pending.pop(future)
            try:
                content = future.result()
                self._upsert_file(candidate=candidate, content=content)
                file_count += 1
                write_count += 1
            except Exception as error:
                error_count += 1
                failed_paths.add(candidate.normalized_path)
                self._record_file_error(candidate.path, error)

        return {"file_count": file_count, "error_count": error_count, "write_count": write_count}

    def _load_existing_files(self, root_path: str) -> dict[str, dict[str, object]]:
        """
        対象ルート配下の既存メタデータを一括取得し、差分判定を高速化する。
        LIKE の代わりに範囲クエリを使い B-tree インデックスを活用する。
        """
        prefix_start, prefix_end = get_descendant_path_range(root_path)
        rows = self.connection.execute(
            """
            SELECT id, normalized_path, mtime, size, last_error
            FROM files
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        ).fetchall()
        return {str(row["normalized_path"]): dict(row) for row in rows}

    def _can_skip_existing_file(self, existing: dict[str, object] | None, stat: os.stat_result) -> bool:
        """
        変更のない成功済みファイルは再抽出を省略する。
        """
        if existing is None:
            return False
        if existing.get("last_error"):
            return False
        return float(existing["mtime"]) == stat.st_mtime and int(existing["size"]) == stat.st_size

    def _walk_files(
        self,
        root: Path,
        keyword_set: frozenset[str],
        non_ascii_keywords: list[str],
        *,
        allowed_extensions: frozenset[str],
        max_depth: int,
        current_depth: int = 0,
    ):
        """
        os.scandir ベースの高速ファイル走査。
        除外ディレクトリには再帰せず、深さと拡張子の条件を満たすファイルだけを返す。
        """
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    # 再帰走査なので親パーツは既にチェック済み。現在のエントリ名だけで判定する
                    if self._is_excluded_name(entry.name, keyword_set, non_ascii_keywords):
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        if current_depth < max_depth:
                            yield from self._walk_files(
                                Path(entry.path),
                                keyword_set,
                                non_ascii_keywords,
                                allowed_extensions=allowed_extensions,
                                max_depth=max_depth,
                                current_depth=current_depth + 1,
                            )
                        continue

                    if entry.is_file(follow_symlinks=False):
                        suffix = os.path.splitext(entry.name)[1].lower()
                        if suffix in allowed_extensions:
                            yield Path(entry.path)
        except PermissionError:
            pass

    def _upsert_file(self, *, candidate: IndexedFileCandidate, content: str | None) -> None:
        """
        ファイルメタデータと本文セグメントを upsert する。
        画像など本文を持たないファイルは files テーブルだけへ登録する。
        """
        indexed_at = datetime.now(UTC).isoformat()
        if candidate.existing_id is not None:
            file_id = candidate.existing_id
            self.connection.execute(
                """
                UPDATE files
                SET full_path = ?, file_name = ?, file_ext = ?,
                    mtime = ?, size = ?, indexed_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    candidate.normalized_path,
                    candidate.path.name,
                    candidate.path.suffix.lower(),
                    candidate.mtime,
                    candidate.size,
                    indexed_at,
                    file_id,
                ),
            )
            # 明示的 DELETE で FTS5 の AFTER DELETE トリガーを確実に発火させる
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
                    candidate.normalized_path,
                    candidate.normalized_path,
                    candidate.path.name,
                    candidate.path.suffix.lower(),
                    candidate.mtime,
                    candidate.size,
                    indexed_at,
                ),
            )
            file_id = int(cursor.lastrowid)

        if content is not None and content.strip():
            self.connection.execute(
                """
                INSERT INTO file_segments(file_id, segment_type, segment_label, content)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, "body", candidate.normalized_path, content),
            )

    def _record_file_error(self, path: Path, error: Exception) -> None:
        normalized_path = path.resolve().as_posix()
        error_message = str(error)
        row = self.connection.execute("SELECT id FROM files WHERE normalized_path = ?", (normalized_path,)).fetchone()
        if row is not None:
            self.connection.execute(
                "UPDATE files SET last_error = ? WHERE id = ?",
                (error_message, int(row["id"])),
            )
        self.connection.execute(
            """
            INSERT INTO failed_files(normalized_path, file_name, error_message, last_failed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(normalized_path) DO UPDATE SET
                file_name = excluded.file_name,
                error_message = excluded.error_message,
                last_failed_at = excluded.last_failed_at
            """,
            (
                normalized_path,
                path.name,
                error_message,
                datetime.now(UTC).isoformat(),
            ),
        )

    def _remove_deleted_files(self, normalized_paths: set[str], *, root_path: str) -> None:
        """
        DB 上に存在するが今回の走査範囲に含まれなくなったレコードをバッチ削除する。
        file_segments を先に明示的に DELETE して FTS5 トリガーを発火させてから files を削除する。
        """
        prefix_start, prefix_end = get_descendant_path_range(root_path)
        rows = self.connection.execute(
            "SELECT id, normalized_path FROM files WHERE normalized_path >= ? AND normalized_path < ?",
            (prefix_start, prefix_end),
        ).fetchall()
        deleted_ids = [int(row["id"]) for row in rows if row["normalized_path"] not in normalized_paths]
        if not deleted_ids:
            return

        chunk_size = 500
        for i in range(0, len(deleted_ids), chunk_size):
            chunk = deleted_ids[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            # file_segments を先に削除して FTS5 の AFTER DELETE トリガーを発火させる
            self.connection.execute(f"DELETE FROM file_segments WHERE file_id IN ({placeholders})", chunk)
            self.connection.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)
        self.connection.commit()

    def _clear_resolved_failed_files(self, *, root_path: str, failed_paths: set[str]) -> None:
        """
        今回失敗していない過去ログを対象ルート配下から掃除する。
        成功済み・削除済みファイルが一覧に残り続けないようにする。
        """
        prefix_start, prefix_end = get_descendant_path_range(root_path)
        rows = self.connection.execute(
            """
            SELECT normalized_path
            FROM failed_files
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        ).fetchall()
        stale_paths = [str(row["normalized_path"]) for row in rows if str(row["normalized_path"]) not in failed_paths]
        if not stale_paths:
            return
        chunk_size = 500
        for index in range(0, len(stale_paths), chunk_size):
            chunk = stale_paths[index:index + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            self.connection.execute(f"DELETE FROM failed_files WHERE normalized_path IN ({placeholders})", chunk)

    def _mark_target_indexed(
        self,
        target_id: int,
        *,
        exclude_keywords: str,
        index_depth: int,
        selected_extensions: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE targets
            SET last_indexed_at = ?, exclude_keywords = ?, index_depth = ?, selected_extensions = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, exclude_keywords, index_depth, selected_extensions, now, target_id),
        )
        self.connection.commit()

    def _count_target_files(self, root_path: str, *, index_depth: int, selected_extensions: str) -> int:
        """
        現在の対象条件に一致するファイル数を返す。
        """
        prefix_start, prefix_end = get_descendant_path_range(root_path)
        descendant_prefix = get_descendant_path_prefix(root_path)
        depth_expression = (
            "(length(normalized_path) - length(replace(normalized_path, '/', '')))"
            " - (length(?) - length(replace(?, '/', '')))"
        )
        filters = ["normalized_path >= ?", "normalized_path < ?", f"{depth_expression} <= ?"]
        values: list[object] = [prefix_start, prefix_end, descendant_prefix, descendant_prefix, index_depth]

        extensions = sorted(normalize_extension_filter(selected_extensions))
        placeholders = ", ".join("?" for _ in extensions)
        filters.append(f"file_ext IN ({placeholders})")
        values.extend(extensions)

        row = self.connection.execute(
            f"SELECT COUNT(*) AS count FROM files WHERE {' AND '.join(filters)}",
            tuple(values),
        ).fetchone()
        return int(row["count"]) if row else 0

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
        """
        インデックス実行ステータスを更新する。
        """
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

    def _normalize_selected_extensions(self, value: str | None) -> str:
        return ",".join(sorted(normalize_extension_filter(value)))

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
        """
        パスの各パートが除外キーワードに一致するか判定する。検索サービスからも利用される。
        """
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
        """
        事前計算済みキーワード集合を用いてパス全体の除外判定を行う。
        """
        return any(self._is_excluded_name(part, keyword_set, non_ascii_keywords) for part in path.parts)

    def _is_excluded_name(self, name: str, keyword_set: frozenset[str], non_ascii_keywords: list[str]) -> bool:
        """
        ディレクトリ名/ファイル名が除外キーワードに一致するか判定する。
        keyword_set による O(1) ルックアップで高速化。
        """
        lower_name = name.lower()
        stripped_name = lower_name.lstrip(".")
        if lower_name in keyword_set or stripped_name in keyword_set:
            return True
        for kw in non_ascii_keywords:
            if kw in lower_name:
                return True
        tokens = set(self._split_ascii_tokens(lower_name))
        return bool(tokens & keyword_set)

    def _split_ascii_tokens(self, value: str) -> list[str]:
        """
        ASCII 記号で区切られたトークン列を返す。
        """
        token = []
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
