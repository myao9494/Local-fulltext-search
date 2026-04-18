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
import threading
from concurrent.futures import ALL_COMPLETED, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from fastapi import HTTPException, status

from app.config import settings
from app.db.connection import ensure_data_dir
from app.db.connection import get_connection
from app.db.schema import reset_schema
from app.extractors.text_extractor import (
    extract_text,
    normalize_extension_token,
    normalize_extension_filter,
    resolve_supported_extension,
    supports_content_extraction,
)
from app.models.indexing import (
    AppSettingsResponse,
    DEFAULT_EXCLUDE_KEYWORDS,
    DeleteIndexedFoldersResponse,
    FailedFileItem,
    FailedFileListResponse,
    IndexedTargetItem,
    IndexedTargetListResponse,
    IndexStatusResponse,
)
from app.services.cjk_bigram import build_cjk_bigram_index_content
from app.services.path_service import (
    AbsolutePathRequiredError,
    get_descendant_path_range,
    normalize_path,
)


@dataclass(frozen=True)
class IndexedFileCandidate:
    """
    インデックス対象ファイルの事前計算済みメタデータを保持する。
    """

    path: Path
    normalized_path: str
    created_at: float
    mtime: float
    size: int
    file_ext: str
    existing_id: int | None


class IndexingCancelledError(Exception):
    """
    利用者がインデックス中止を要求したことを表す。
    """


class IndexRunController:
    """
    共有DB接続ごとに、インデックス中止要求の状態を保持する。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel_requested = False

    def reset(self) -> None:
        with self._lock:
            self._cancel_requested = False

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True

    def is_cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested


_CONTROLLERS_LOCK = threading.Lock()
_CONTROLLERS: dict[int, IndexRunController] = {}
CURRENT_TARGET_INDEX_VERSION = 1


class IndexService:
    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()

    def reset_database(self) -> None:
        """
        インデックス DB を空の初期状態へ戻す。
        検索結果・対象キャッシュ・失敗履歴をすべて削除し、スキーマだけを再作成する。
        """
        if self._is_running():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Indexing is already running.")
        reset_schema(self.connection)

    def ensure_fresh_target(
        self,
        *,
        full_path: str,
        refresh_window_minutes: int,
        exclude_keywords: str | None = None,
        index_depth: int = 1,
        types: str | None = None,
    ) -> None:
        if self._is_running():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Indexing is already running.")

        app_settings = self.get_app_settings()
        normalized_keywords = self._normalize_exclude_keywords(exclude_keywords)
        normalized_extensions = self._normalize_selected_extensions(
            types,
            custom_content_extensions=app_settings.custom_content_extensions,
            custom_filename_extensions=app_settings.custom_filename_extensions,
        )

        total_files = 0
        error_count = 0
        try:
            target = self._ensure_target(
                full_path=full_path,
                exclude_keywords=normalized_keywords,
                index_depth=index_depth,
                selected_extensions=normalized_extensions,
            )
            effective_keywords = self._merge_exclude_keyword_strings(
                normalized_keywords,
                str(target.get("exclude_keywords") or ""),
            )
            needs_refresh = self._needs_refresh(
                target,
                refresh_window_minutes,
                effective_keywords,
                index_depth,
                normalized_extensions,
            )
            if not needs_refresh:
                return

            controller = self._get_run_controller()
            controller.reset()
            started_at = datetime.now(UTC).isoformat()
            self._update_status(is_running=True, cancel_requested=False, last_started_at=started_at, last_error=None)

            if needs_refresh:
                stats = self._index_target(
                    target,
                    effective_keywords,
                    controller=controller,
                    index_depth=index_depth,
                    selected_extensions=normalized_extensions,
                    custom_content_extensions=app_settings.custom_content_extensions,
                    custom_filename_extensions=app_settings.custom_filename_extensions,
                )
                total_files = stats["file_count"]
                error_count = stats["error_count"]
                self._mark_target_indexed(
                    int(target["id"]),
                    exclude_keywords=str(stats["exclude_keywords"]),
                    index_depth=index_depth,
                    selected_extensions=normalized_extensions,
                    indexed_file_count=total_files,
                )
        except IndexingCancelledError as error:
            self._update_status(
                is_running=False,
                cancel_requested=False,
                last_finished_at=datetime.now(UTC).isoformat(),
                total_files=total_files,
                error_count=error_count,
                last_error=None,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except Exception as error:
            self._update_status(
                is_running=False,
                cancel_requested=False,
                last_finished_at=datetime.now(UTC).isoformat(),
                last_error=str(error),
                total_files=total_files,
                error_count=error_count + 1,
            )
            raise

        self._update_status(
            is_running=False,
            cancel_requested=False,
            last_finished_at=datetime.now(UTC).isoformat(),
            total_files=total_files,
            error_count=error_count,
            last_error=None,
        )

    def cancel_indexing(self) -> None:
        """
        実行中インデックスへ中止要求を送る。
        """
        self._get_run_controller().request_cancel()
        self._update_status(cancel_requested=True)

    def get_status(self) -> IndexStatusResponse:
        row = self.connection.execute(
            """
            SELECT last_started_at, last_finished_at, total_files, error_count, is_running, last_error
                   , cancel_requested
            FROM index_runs
            WHERE id = 1
            """
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Index status unavailable.")
        return IndexStatusResponse.model_validate(dict(row))

    def get_app_settings(self) -> AppSettingsResponse:
        """
        アプリ全体で共有する設定値を返す。
        """
        custom_content_extensions = self._read_persisted_custom_content_extensions()
        custom_filename_extensions = self._read_persisted_custom_filename_extensions()
        return AppSettingsResponse(
            exclude_keywords=self._read_persisted_exclude_keywords(),
            synonym_groups=self._read_persisted_synonym_groups(),
            index_selected_extensions=self._read_persisted_index_selected_extensions(
                custom_content_extensions=custom_content_extensions,
                custom_filename_extensions=custom_filename_extensions,
            ),
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
        )

    def update_app_settings(
        self,
        *,
        exclude_keywords: str | None = None,
        synonym_groups: str | None = None,
        index_selected_extensions: str | None = None,
        custom_content_extensions: str | None = None,
        custom_filename_extensions: str | None = None,
    ) -> AppSettingsResponse:
        """
        アプリ全体で共有する設定値を更新し、保存後の値を返す。
        """
        current = self.get_app_settings()
        normalized_exclude_keywords = (
            self._normalize_exclude_keywords(exclude_keywords) if exclude_keywords is not None else current.exclude_keywords
        )
        normalized_synonym_groups = (
            self._normalize_synonym_groups(synonym_groups) if synonym_groups is not None else current.synonym_groups
        )
        normalized_custom_content_extensions = (
            self._normalize_extension_entries(custom_content_extensions)
            if custom_content_extensions is not None
            else current.custom_content_extensions
        )
        normalized_custom_filename_extensions = (
            self._normalize_extension_entries(custom_filename_extensions)
            if custom_filename_extensions is not None
            else current.custom_filename_extensions
        )
        normalized_index_selected_extensions = (
            self._normalize_selected_extensions(
                index_selected_extensions,
                custom_content_extensions=normalized_custom_content_extensions,
                custom_filename_extensions=normalized_custom_filename_extensions,
            )
            if index_selected_extensions is not None
            else self._normalize_selected_extensions(
                current.index_selected_extensions,
                custom_content_extensions=normalized_custom_content_extensions,
                custom_filename_extensions=normalized_custom_filename_extensions,
            )
        )
        self._write_persisted_exclude_keywords(normalized_exclude_keywords)
        self._write_persisted_synonym_groups(normalized_synonym_groups)
        self._write_persisted_custom_content_extensions(normalized_custom_content_extensions)
        self._write_persisted_custom_filename_extensions(normalized_custom_filename_extensions)
        self._write_persisted_index_selected_extensions(normalized_index_selected_extensions)
        return AppSettingsResponse(
            exclude_keywords=normalized_exclude_keywords,
            synonym_groups=normalized_synonym_groups,
            index_selected_extensions=normalized_index_selected_extensions,
            custom_content_extensions=normalized_custom_content_extensions,
            custom_filename_extensions=normalized_custom_filename_extensions,
        )

    def _read_persisted_exclude_keywords(self) -> str:
        """
        除外キーワードは人が直接編集しやすいテキストファイルから読み込む。
        旧 SQLite 保存値が残っている場合は初回だけテキストへ移行する。
        """
        ensure_data_dir()
        path = settings.exclude_keywords_path
        if path.exists():
            return self._normalize_exclude_keywords(path.read_text(encoding="utf-8"))

        legacy_keywords = self._read_legacy_exclude_keywords_from_db()
        initial_value = self._normalize_exclude_keywords(legacy_keywords or DEFAULT_EXCLUDE_KEYWORDS)
        self._write_persisted_exclude_keywords(initial_value)
        return initial_value

    def _write_persisted_exclude_keywords(self, value: str) -> None:
        """
        除外キーワードを改行区切りのプレーンテキストとして保存する。
        """
        ensure_data_dir()
        path = settings.exclude_keywords_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._normalize_exclude_keywords(value), encoding="utf-8")

    def _read_persisted_synonym_groups(self) -> str:
        """
        同義語リストは 1 行 1 グループのテキストファイルから読み込む。
        """
        ensure_data_dir()
        path = settings.synonym_groups_path
        if path.exists():
            return self._normalize_synonym_groups(path.read_text(encoding="utf-8"))

        self._write_persisted_synonym_groups("")
        return ""

    def _write_persisted_synonym_groups(self, value: str) -> None:
        """
        同義語リストをカンマ区切り・1 行 1 グループのプレーンテキストとして保存する。
        """
        ensure_data_dir()
        path = settings.synonym_groups_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._normalize_synonym_groups(value), encoding="utf-8")

    def _read_persisted_custom_content_extensions(self) -> str:
        """
        本文抽出対象として追加した拡張子一覧をテキストファイルから読み込む。
        """
        return self._read_persisted_extension_file(settings.custom_content_extensions_path)

    def _write_persisted_custom_content_extensions(self, value: str) -> None:
        """
        本文抽出対象の追加拡張子一覧をテキストファイルへ保存する。
        """
        self._write_persisted_extension_file(settings.custom_content_extensions_path, value)

    def _read_persisted_custom_filename_extensions(self) -> str:
        """
        ファイル名のみ検索対象として追加した拡張子一覧をテキストファイルから読み込む。
        """
        return self._read_persisted_extension_file(settings.custom_filename_extensions_path)

    def _write_persisted_custom_filename_extensions(self, value: str) -> None:
        """
        ファイル名のみ検索対象の追加拡張子一覧をテキストファイルへ保存する。
        """
        self._write_persisted_extension_file(settings.custom_filename_extensions_path, value)

    def _read_persisted_index_selected_extensions(
        self,
        *,
        custom_content_extensions: str,
        custom_filename_extensions: str,
    ) -> str:
        """
        インデックス対象として有効化された拡張子一覧をテキストファイルから読み込む。
        初回は現在サポートしている全拡張子を既定値として保存する。
        """
        ensure_data_dir()
        path = settings.index_selected_extensions_path
        if path.exists():
            return self._normalize_selected_extensions(
                path.read_text(encoding="utf-8"),
                custom_content_extensions=custom_content_extensions,
                custom_filename_extensions=custom_filename_extensions,
            )

        initial_value = self._normalize_selected_extensions(
            None,
            custom_content_extensions=custom_content_extensions,
            custom_filename_extensions=custom_filename_extensions,
        )
        self._write_persisted_index_selected_extensions(initial_value)
        return initial_value

    def _write_persisted_index_selected_extensions(self, value: str) -> None:
        """
        インデックス対象として有効化された拡張子一覧をテキストファイルへ保存する。
        """
        self._write_persisted_extension_file(settings.index_selected_extensions_path, value)

    def _read_persisted_extension_file(self, path: Path) -> str:
        """
        拡張子一覧ファイルを読み込み、未作成なら空ファイルを作って返す。
        """
        ensure_data_dir()
        if path.exists():
            return self._normalize_extension_entries(path.read_text(encoding="utf-8"))

        self._write_persisted_extension_file(path, "")
        return ""

    def _write_persisted_extension_file(self, path: Path, value: str) -> None:
        """
        拡張子一覧ファイルを正規化して保存する。
        """
        ensure_data_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._normalize_extension_entries(value), encoding="utf-8")

    def _read_legacy_exclude_keywords_from_db(self) -> str | None:
        """
        以前の SQLite 保存方式から 1 回だけ値を移行するための後方互換読み込み。
        """
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()
        if table_exists is None:
            return None
        row = self.connection.execute(
            """
            SELECT exclude_keywords
            FROM app_settings
            WHERE id = 1
            """
        ).fetchone()
        if row is None:
            return None
        return str(row["exclude_keywords"])

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

    def list_indexed_targets(self) -> IndexedTargetListResponse:
        """
        UI 向けに、実際にインデックス済みファイルが存在する全フォルダ一覧を返す。
        """
        rows = self.connection.execute(
            """
            SELECT
                normalized_path,
                indexed_at
            FROM files
            ORDER BY normalized_path ASC
            """
        ).fetchall()
        target_rows = self.connection.execute(
            """
            SELECT full_path
            FROM targets
            WHERE last_indexed_at IS NOT NULL
            ORDER BY length(full_path) DESC
            """
        ).fetchall()
        target_roots = [str(row["full_path"]) for row in target_rows]
        folder_map: dict[str, dict[str, object]] = {}
        for row in rows:
            file_path = normalize_path(str(row["normalized_path"]))
            for folder_path in self._expand_indexed_folder_paths(file_path, target_roots):
                folder_entry = folder_map.get(folder_path)
                indexed_at = row["indexed_at"]
                if folder_entry is None:
                    folder_map[folder_path] = {
                        "full_path": folder_path,
                        "last_indexed_at": indexed_at,
                        "indexed_file_count": 1,
                    }
                    continue
                folder_entry["indexed_file_count"] = int(folder_entry["indexed_file_count"]) + 1
                current_last = folder_entry["last_indexed_at"]
                if current_last is None or str(indexed_at) > str(current_last):
                    folder_entry["last_indexed_at"] = indexed_at

        items = [
            IndexedTargetItem.model_validate(item)
            for item in sorted(
                folder_map.values(),
                key=lambda item: (str(item["last_indexed_at"]), str(item["full_path"])),
                reverse=True,
            )
        ]
        return IndexedTargetListResponse(items=items)

    def delete_indexed_folders(self, folder_paths: list[str]) -> DeleteIndexedFoldersResponse:
        """
        選択したフォルダ群配下のインデックスを削除し、重なる targets は次回再取得される状態へ戻す。
        """
        if self._is_running():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Indexing is already running.")
        normalized_paths = sorted(
            {
                normalize_path(folder_path).as_posix()
                for folder_path in folder_paths
                if str(folder_path).strip()
            }
        )
        if not normalized_paths:
            return DeleteIndexedFoldersResponse(deleted_count=0)

        for folder_path in normalized_paths:
            self._delete_target_related_rows(folder_path)
            self._mark_overlapping_targets_stale(folder_path)

        self.connection.commit()
        return DeleteIndexedFoldersResponse(deleted_count=len(normalized_paths))

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
        try:
            normalized_path = normalize_path(full_path)
        except AbsolutePathRequiredError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Folder path must be an absolute path or Windows UNC path.",
            ) from error
        if not normalized_path.exists() or not normalized_path.is_dir():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder path must be an existing directory.")

        row = self.connection.execute(
            """
            SELECT
                id, full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions,
                indexed_file_count, index_version, created_at, updated_at
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
                full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions,
                indexed_file_count, index_version, created_at, updated_at
            )
            VALUES (?, NULL, ?, ?, ?, 0, 0, ?, ?)
            """,
            (normalized_path.as_posix(), exclude_keywords, index_depth, selected_extensions, now, now),
        )
        self.connection.commit()
        created = self.connection.execute(
            """
            SELECT
                id, full_path, last_indexed_at, exclude_keywords, index_depth, selected_extensions,
                indexed_file_count, index_version, created_at, updated_at
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
        if int(target.get("index_version") or 0) < CURRENT_TARGET_INDEX_VERSION:
            return True
        indexed_at = datetime.fromisoformat(str(last_indexed_at))
        elapsed_seconds = (datetime.now(UTC) - indexed_at).total_seconds()
        return elapsed_seconds > refresh_window_minutes * 60

    def _index_target(
        self,
        target: dict[str, object],
        exclude_keywords: str,
        controller: IndexRunController,
        *,
        index_depth: int,
        selected_extensions: str,
        custom_content_extensions: str,
        custom_filename_extensions: str,
    ) -> dict[str, object]:
        """
        指定ターゲット配下を高速に再走査する。
        走査は os.scandir、本文抽出はスレッド並列、DB 書き込みは直列でまとめる。
        """
        folder_path = normalize_path(str(target["full_path"]))
        normalized_paths: set[str] = set()
        failed_paths: set[str] = set()
        auto_excluded_paths: set[str] = set()
        file_count = 0
        error_count = 0
        write_count = 0

        keywords = self._parse_exclude_keywords(exclude_keywords)
        keyword_set, non_ascii_keywords, excluded_path_prefixes = self._compile_exclude_keywords(keywords)
        custom_content_extension_list = tuple(self._parse_extension_entries(custom_content_extensions))
        custom_filename_extension_list = tuple(self._parse_extension_entries(custom_filename_extensions))
        allowed_extensions = normalize_extension_filter(
            selected_extensions,
            extra_content_extensions=custom_content_extension_list,
            extra_filename_extensions=custom_filename_extension_list,
        )
        existing_files = self._load_existing_files(folder_path.as_posix())
        batch_size = 100
        max_workers = self._resolve_extract_worker_count()
        max_pending = max_workers * 4
        pending: dict[Future[str], IndexedFileCandidate] = {}

        executor = ThreadPoolExecutor(max_workers=max_workers)
        cancelled = False
        try:
            for path in self._walk_files(
                folder_path,
                keyword_set,
                non_ascii_keywords,
                excluded_path_prefixes=excluded_path_prefixes,
                auto_excluded_paths=auto_excluded_paths,
                allowed_extensions=allowed_extensions,
                max_depth=index_depth,
            ):
                self._raise_if_cancel_requested(controller)
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
                    created_at=self._resolve_created_at(stat),
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    file_ext=resolve_supported_extension(
                        path,
                        extra_content_extensions=custom_content_extension_list,
                        extra_filename_extensions=custom_filename_extension_list,
                    )
                    or path.suffix.lower(),
                    existing_id=int(existing["id"]) if existing is not None else None,
                )

                if supports_content_extraction(
                    path,
                    extra_content_extensions=custom_content_extension_list,
                    extra_filename_extensions=custom_filename_extension_list,
                ):
                    pending[
                        executor.submit(
                            extract_text,
                            path,
                            extra_content_extensions=custom_content_extension_list,
                            extra_filename_extensions=custom_filename_extension_list,
                        )
                    ] = candidate
                    if len(pending) >= max_pending:
                        result = self._drain_pending_futures(
                            pending,
                            failed_paths,
                            controller=controller,
                            drain_all=False,
                        )
                        file_count += result["file_count"]
                        error_count += result["error_count"]
                        write_count += result["write_count"]
                else:
                    self._upsert_file(candidate=candidate, content=None)
                    file_count += 1
                    write_count += 1
                    if write_count % batch_size == 0:
                        self.connection.commit()

            result = self._drain_pending_futures(
                pending,
                failed_paths,
                controller=controller,
                drain_all=True,
            )
            file_count += result["file_count"]
            error_count += result["error_count"]
            write_count += result["write_count"]
        except IndexingCancelledError:
            cancelled = True
            self.connection.commit()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not cancelled:
            self.connection.commit()
            self._remove_deleted_files(normalized_paths, root_path=folder_path.as_posix())
            self._clear_resolved_failed_files(root_path=folder_path.as_posix(), failed_paths=failed_paths)
        return {
            "file_count": file_count,
            "error_count": error_count,
            "exclude_keywords": self._normalize_keyword_list([*keywords, *sorted(auto_excluded_paths)]),
        }

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
        controller: IndexRunController,
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
            self._raise_if_cancel_requested(controller)
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

    def _raise_if_cancel_requested(self, controller: IndexRunController) -> None:
        """
        中止要求が来ていたら即座に処理を打ち切る。
        """
        if controller.is_cancel_requested():
            raise IndexingCancelledError("Indexing was cancelled.")

    def _get_run_controller(self) -> IndexRunController:
        """
        共有DB接続単位で中止要求コントローラを再利用する。
        """
        connection_key = id(self.connection)
        with _CONTROLLERS_LOCK:
            controller = _CONTROLLERS.get(connection_key)
            if controller is None:
                controller = IndexRunController()
                _CONTROLLERS[connection_key] = controller
            return controller

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
        excluded_path_prefixes: tuple[str, ...],
        auto_excluded_paths: set[str],
        allowed_extensions: frozenset[str],
        max_depth: int,
        current_depth: int = 0,
    ):
        """
        os.scandir ベースの高速ファイル走査。
        除外ディレクトリには再帰せず、深さと拡張子の条件を満たすファイルだけを返す。
        """
        normalized_root = self._normalize_excluded_path_prefix(root)
        if normalized_root is not None and self._is_excluded_path_prefix(normalized_root, excluded_path_prefixes):
            return

        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    # 再帰走査なので親パーツは既にチェック済み。現在のエントリ名だけで判定する
                    if self._is_excluded_name(entry.name, keyword_set, non_ascii_keywords):
                        continue

                    normalized_entry_path = self._normalize_excluded_path_prefix(entry.path)
                    if normalized_entry_path is not None and self._is_excluded_path_prefix(
                        normalized_entry_path,
                        excluded_path_prefixes,
                    ):
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        if current_depth < max_depth:
                            yield from self._walk_files(
                                Path(entry.path),
                                keyword_set,
                                non_ascii_keywords,
                                excluded_path_prefixes=excluded_path_prefixes,
                                auto_excluded_paths=auto_excluded_paths,
                                allowed_extensions=allowed_extensions,
                                max_depth=max_depth,
                                current_depth=current_depth + 1,
                            )
                        continue

                    if entry.is_file(follow_symlinks=False):
                        resolved_extension = next(
                            (extension for extension in sorted(allowed_extensions, key=len, reverse=True) if entry.name.lower().endswith(extension)),
                            None,
                        )
                        if resolved_extension in allowed_extensions:
                            yield Path(entry.path)
        except PermissionError:
            pass
        except OSError as error:
            if self._is_unexpected_network_error(error):
                if normalized_root is not None:
                    auto_excluded_paths.add(normalized_root)
                return
            raise

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
                    created_at = ?, mtime = ?, size = ?, indexed_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    candidate.normalized_path,
                    candidate.path.name,
                    candidate.file_ext,
                    candidate.created_at,
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
                    file_name, file_ext, created_at, mtime, size, indexed_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    candidate.normalized_path,
                    candidate.normalized_path,
                    candidate.path.name,
                    candidate.file_ext,
                    candidate.created_at,
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
            cjk_bigram_content = build_cjk_bigram_index_content(content)
            if cjk_bigram_content:
                self.connection.execute(
                    """
                    INSERT INTO file_segments(file_id, segment_type, segment_label, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (file_id, "cjk_bigram", candidate.normalized_path, cjk_bigram_content),
                )

    def _resolve_created_at(self, stat: os.stat_result) -> float:
        """
        作成日時が取得できる環境では birth time を優先し、未対応環境では ctime へフォールバックする。
        Linux では ctime が inode 変更時刻のため厳密な作成日ではないが、列を常に埋めて検索条件を維持する。
        """
        birth_time = getattr(stat, "st_birthtime", None)
        if isinstance(birth_time, (int, float)):
            return float(birth_time)
        return float(stat.st_ctime)

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

    def _delete_target_related_rows(self, root_path: str) -> None:
        """
        対象フォルダ配下の files / file_segments / failed_files をまとめて削除する。
        """
        prefix_start, prefix_end = get_descendant_path_range(root_path)
        rows = self.connection.execute(
            """
            SELECT id
            FROM files
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        ).fetchall()
        file_ids = [int(row["id"]) for row in rows]
        if file_ids:
            chunk_size = 500
            for index in range(0, len(file_ids), chunk_size):
                chunk = file_ids[index:index + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                self.connection.execute(f"DELETE FROM file_segments WHERE file_id IN ({placeholders})", chunk)
                self.connection.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)

        self.connection.execute(
            """
            DELETE FROM failed_files
            WHERE normalized_path >= ? AND normalized_path < ?
            """,
            (prefix_start, prefix_end),
        )

    def _mark_overlapping_targets_stale(self, folder_path: str) -> None:
        """
        削除対象と重なる targets は、次回検索時に必ず再インデックスされるよう last_indexed_at を外す。
        """
        rows = self.connection.execute(
            """
            SELECT id, full_path
            FROM targets
            """
        ).fetchall()
        now = datetime.now(UTC).isoformat()
        for row in rows:
            target_path = str(row["full_path"])
            if self._paths_overlap(folder_path, target_path):
                self.connection.execute(
                    """
                    UPDATE targets
                    SET last_indexed_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, int(row["id"])),
                )

    def _expand_indexed_folder_paths(self, file_path: Path, target_roots: list[str]) -> list[str]:
        """
        ファイルから、最も近い target までの祖先フォルダを展開する。
        """
        file_path_str = file_path.as_posix()
        limit_path = self._find_nearest_target_root(file_path_str, target_roots)
        folders: list[str] = []
        current = file_path.parent
        while True:
            folders.append(current.as_posix())
            if current.as_posix() == limit_path or current.parent == current:
                break
            current = current.parent
        return folders

    def _find_nearest_target_root(self, file_path: str, target_roots: list[str]) -> str:
        """
        指定ファイルを含む最も深い target ルートを返す。
        """
        for root_path in target_roots:
            if file_path == root_path or file_path.startswith(f"{root_path}/"):
                return root_path
        return Path(file_path).parent.as_posix()

    def _paths_overlap(self, left: str, right: str) -> bool:
        """
        フォルダどうしが同一または祖先・子孫関係にあるかを判定する。
        """
        return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")

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
        indexed_file_count: int,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE targets
            SET last_indexed_at = ?, exclude_keywords = ?, index_depth = ?, selected_extensions = ?,
                indexed_file_count = ?, index_version = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                exclude_keywords,
                index_depth,
                selected_extensions,
                indexed_file_count,
                CURRENT_TARGET_INDEX_VERSION,
                now,
                target_id,
            ),
        )
        self.connection.commit()

    def _update_status(
        self,
        *,
        is_running: bool | None = None,
        cancel_requested: bool | None = None,
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
            SET is_running = COALESCE(?, is_running),
                cancel_requested = COALESCE(?, cancel_requested),
                last_started_at = COALESCE(?, last_started_at),
                last_finished_at = COALESCE(?, last_finished_at),
                last_error = ?,
                total_files = COALESCE(?, total_files),
                error_count = COALESCE(?, error_count)
            WHERE id = 1
            """,
            (
                int(is_running) if is_running is not None else None,
                int(cancel_requested) if cancel_requested is not None else None,
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

    def _normalize_keyword_list(self, keywords: list[str]) -> str:
        return "\n".join(self._parse_exclude_keywords("\n".join(keywords)))

    def _normalize_extension_entries(self, value: str | None) -> str:
        return "\n".join(self._parse_extension_entries(value))

    def _normalize_synonym_groups(self, value: str | None) -> str:
        return "\n".join(",".join(group) for group in self._parse_synonym_groups(value))

    def _normalize_selected_extensions(
        self,
        value: str | None,
        *,
        custom_content_extensions: str = "",
        custom_filename_extensions: str = "",
    ) -> str:
        return "\n".join(
            sorted(
                normalize_extension_filter(
                    value,
                    extra_content_extensions=tuple(self._parse_extension_entries(custom_content_extensions)),
                    extra_filename_extensions=tuple(self._parse_extension_entries(custom_filename_extensions)),
                )
            )
        )

    def _merge_exclude_keyword_strings(self, *values: str) -> str:
        merged: list[str] = []
        for value in values:
            merged.extend(self._parse_exclude_keywords(value))
        return self._normalize_keyword_list(merged)

    def _parse_exclude_keywords(self, value: str | None) -> list[str]:
        seen: set[str] = set()
        keywords: list[str] = []
        for line in (value or "").splitlines():
            keyword = line.strip()
            normalized_keyword = (
                keyword if self._normalize_excluded_path_prefix(keyword) is not None else keyword.lower()
            )
            if not keyword or normalized_keyword in seen:
                continue
            seen.add(normalized_keyword)
            keywords.append(keyword)
        return keywords

    def _parse_extension_entries(self, value: str | None) -> list[str]:
        seen: set[str] = set()
        extensions: list[str] = []
        for raw_token in (value or "").replace(",", "\n").splitlines():
            extension = normalize_extension_token(raw_token)
            if not extension or extension in seen:
                continue
            seen.add(extension)
            extensions.append(extension)
        return extensions

    def _parse_synonym_groups(self, value: str | None) -> list[list[str]]:
        """
        同義語リストは 1 行を 1 グループとして解釈し、カンマ区切りで重複を除去する。
        ASCII は大文字小文字違いを同一語として扱い、元の表記は先勝ちで残す。
        """
        groups: list[list[str]] = []
        for line in (value or "").splitlines():
            seen: set[str] = set()
            group: list[str] = []
            for raw_token in line.replace("，", ",").split(","):
                token = raw_token.strip()
                normalized_token = token.casefold()
                if not token or normalized_token in seen:
                    continue
                seen.add(normalized_token)
                group.append(token)
            if group:
                groups.append(group)
        return groups

    def _should_exclude_path(self, path: Path, keywords: list[str]) -> bool:
        """
        パスの各パートが除外キーワードに一致するか判定する。検索サービスからも利用される。
        """
        if not keywords:
            return False
        keyword_set, non_ascii_keywords, excluded_path_prefixes = self._compile_exclude_keywords(keywords)
        return self._should_exclude_path_with_keywords(path, keyword_set, non_ascii_keywords, excluded_path_prefixes)

    def _should_exclude_path_with_keywords(
        self,
        path: Path,
        keyword_set: frozenset[str],
        non_ascii_keywords: list[str],
        excluded_path_prefixes: tuple[str, ...],
    ) -> bool:
        """
        事前計算済みキーワード集合を用いてパス全体の除外判定を行う。
        """
        normalized_path = self._normalize_excluded_path_prefix(path)
        if normalized_path is not None and self._is_excluded_path_prefix(normalized_path, excluded_path_prefixes):
            return True
        return any(self._is_excluded_name(part, keyword_set, non_ascii_keywords) for part in path.parts)

    def _compile_exclude_keywords(self, keywords: list[str]) -> tuple[frozenset[str], list[str], tuple[str, ...]]:
        """
        名前一致用キーワードとフルパス除外用プレフィックスを分離して前処理する。
        """
        name_keywords: list[str] = []
        path_prefixes: list[str] = []
        for keyword in keywords:
            normalized_path = self._normalize_excluded_path_prefix(keyword)
            if normalized_path is not None:
                path_prefixes.append(normalized_path)
                continue
            name_keywords.append(keyword)
        normalized_name_keywords = [keyword.lower() for keyword in name_keywords]
        keyword_set = frozenset(normalized_name_keywords)
        non_ascii_keywords = [kw for kw in normalized_name_keywords if any(ord(c) > 127 for c in kw)]
        return keyword_set, non_ascii_keywords, tuple(path_prefixes)

    def _normalize_excluded_path_prefix(self, value: str | os.PathLike[str] | Path) -> str | None:
        """
        除外キーワードがフルパス形式なら比較しやすい表記へ正規化する。
        """
        raw_value = os.fspath(value).strip()
        if "/" not in raw_value and "\\" not in raw_value:
            return None
        normalized = raw_value.replace("\\", "/")
        if len(normalized) > 1:
            normalized = normalized.rstrip("/")
        return normalized

    def _is_excluded_path_prefix(self, normalized_path: str, excluded_path_prefixes: tuple[str, ...]) -> bool:
        """
        パス全体またはその祖先が除外パスキーワードに一致するか判定する。
        絶対パス指定は先頭一致、相対パス指定は祖先の途中一致を許可する。
        """
        for prefix in excluded_path_prefixes:
            if self._is_hidden_child_path_prefix(prefix):
                if self._matches_hidden_child_path_prefix(normalized_path, prefix):
                    return True
                continue

            if self._is_absolute_excluded_path_prefix(prefix):
                if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
                    return True
                continue

            if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
                return True

            bounded_prefix = f"/{prefix}"
            if normalized_path.endswith(bounded_prefix) or f"{bounded_prefix}/" in normalized_path:
                return True
        return False

    def _is_hidden_child_path_prefix(self, prefix: str) -> bool:
        """
        `foo/.` 形式は、foo 配下のドット始まり要素をまとめて除外するショートハンドとして扱う。
        """
        return prefix.endswith("/.")

    def _matches_hidden_child_path_prefix(self, normalized_path: str, prefix: str) -> bool:
        """
        `foo/.` 形式の除外キーワードが、foo 配下の `.bar` や `.baz/...` に一致するか判定する。
        """
        if normalized_path.startswith(prefix):
            return True

        if self._is_absolute_excluded_path_prefix(prefix):
            return False

        bounded_prefix = f"/{prefix}"
        return normalized_path.endswith(bounded_prefix) or bounded_prefix in normalized_path

    def _is_absolute_excluded_path_prefix(self, prefix: str) -> bool:
        """
        除外パスキーワードが絶対パスかどうかを判定する。
        `/foo/bar` と `c:/foo/bar` の両方を受け付ける。
        """
        if prefix.startswith("/"):
            return True
        return len(prefix) >= 3 and prefix[1] == ":" and prefix[2] == "/"

    def _is_unexpected_network_error(self, error: OSError) -> bool:
        """
        Windows の WinError 59 はアクセス不能な共有先として扱い、以降の走査対象から外す。
        """
        return getattr(error, "winerror", None) == 59

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
