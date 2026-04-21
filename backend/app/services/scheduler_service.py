"""
スケジューラーサービス。
開始日時になったら別プロセスで複数フォルダのインデックスを順次実行し、進捗ログを保持する。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Callable

from fastapi import HTTPException, status

from app.db.connection import get_connection
from app.db.schema import initialize_schema
from app.models.indexing import SchedulerLogItem, SchedulerSettingsResponse
from app.services.index_service import IndexService
from app.services.path_service import AbsolutePathRequiredError, normalize_path


type ProcessFactory = Callable[..., subprocess.Popen[bytes] | subprocess.Popen[str]]


class SchedulerService:
    """
    スケジュール設定・実行状況・ログの永続化を担当する。
    """

    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection or get_connection()

    def get_scheduler_settings(self) -> SchedulerSettingsResponse:
        """
        保存済み設定と最新ログを UI 向けに返す。
        """
        settings_row = self.connection.execute(
            """
            SELECT start_at, is_enabled, updated_at
            FROM scheduler_settings
            WHERE id = 1
            """
        ).fetchone()
        runtime_row = self.connection.execute(
            """
            SELECT status, current_path, last_started_at, last_finished_at, last_error
            FROM scheduler_runtime
            WHERE id = 1
            """
        ).fetchone()
        path_rows = self.connection.execute(
            """
            SELECT folder_path
            FROM scheduler_paths
            WHERE scheduler_id = 1
            ORDER BY sort_order ASC
            """
        ).fetchall()
        log_rows = self.connection.execute(
            """
            SELECT logged_at, level, message, folder_path
            FROM scheduler_logs
            ORDER BY id ASC
            """
        ).fetchall()
        return SchedulerSettingsResponse(
            paths=[str(row["folder_path"]) for row in path_rows],
            start_at=settings_row["start_at"] if settings_row else None,
            is_enabled=bool(settings_row["is_enabled"]) if settings_row else False,
            status=str(runtime_row["status"]) if runtime_row else "idle",
            last_started_at=runtime_row["last_started_at"] if runtime_row else None,
            last_finished_at=runtime_row["last_finished_at"] if runtime_row else None,
            current_path=str(runtime_row["current_path"]) if runtime_row and runtime_row["current_path"] else None,
            last_error=str(runtime_row["last_error"]) if runtime_row and runtime_row["last_error"] else None,
            logs=[SchedulerLogItem.model_validate(dict(row)) for row in log_rows],
        )

    def schedule_indexing(self, *, paths: list[str], start_at: datetime) -> SchedulerSettingsResponse:
        """
        パス一覧と開始日時を保存し、開始ログを初期化して待機状態へ切り替える。
        """
        normalized_paths = self._normalize_scheduler_paths(paths)
        if not normalized_paths:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one folder path is required.")

        start_at_utc = start_at.astimezone(UTC).isoformat()
        now = datetime.now(UTC).isoformat()

        self.connection.execute("DELETE FROM scheduler_paths WHERE scheduler_id = 1")
        for index, folder_path in enumerate(normalized_paths):
            self.connection.execute(
                """
                INSERT INTO scheduler_paths(scheduler_id, folder_path, sort_order)
                VALUES (1, ?, ?)
                """,
                (folder_path, index),
            )

        self.connection.execute("DELETE FROM scheduler_logs")
        self.connection.execute(
            """
            UPDATE scheduler_settings
            SET start_at = ?, is_enabled = 1, updated_at = ?
            WHERE id = 1
            """,
            (start_at_utc, now),
        )
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET status = 'scheduled',
                current_path = NULL,
                process_id = NULL,
                run_token = NULL,
                last_error = NULL
            WHERE id = 1
            """
        )
        self.connection.commit()
        self.append_log(level="info", message=f"スケジュールを開始しました。開始予定: {start_at_utc}")
        return self.get_scheduler_settings()

    def try_start_due_schedule(self, *, process_factory: ProcessFactory | None = None) -> bool:
        """
        開始時刻を過ぎた待機スケジュールがあれば、別プロセスを 1 度だけ起動する。
        """
        row = self.connection.execute(
            """
            SELECT settings.start_at, settings.is_enabled, runtime.status
            FROM scheduler_settings AS settings
            JOIN scheduler_runtime AS runtime ON runtime.id = settings.id
            WHERE settings.id = 1
            """
        ).fetchone()
        if row is None or not bool(row["is_enabled"]) or row["start_at"] is None:
            return False

        status_value = str(row["status"])
        if status_value in {"launching", "running"}:
            return False

        start_at = datetime.fromisoformat(str(row["start_at"]))
        if datetime.now(UTC) < start_at:
            return False

        run_token = uuid.uuid4().hex
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET status = 'launching',
                process_id = NULL,
                run_token = ?,
                current_path = NULL,
                last_error = NULL
            WHERE id = 1
            """,
            (run_token,),
        )
        self.connection.commit()

        backend_dir = Path(__file__).resolve().parents[2]
        factory = process_factory or subprocess.Popen
        process = factory(
            [sys.executable, "-m", "app.services.scheduler_worker", run_token],
            cwd=str(backend_dir),
        )
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET process_id = ?
            WHERE id = 1
            """,
            (process.pid,),
        )
        self.connection.commit()
        return True

    def append_log(self, *, level: str, message: str, folder_path: str | None = None) -> None:
        """
        UI 表示用ログを追記する。
        """
        self.connection.execute(
            """
            INSERT INTO scheduler_logs(logged_at, level, message, folder_path)
            VALUES (?, ?, ?, ?)
            """,
            (datetime.now(UTC).isoformat(), level, message, folder_path),
        )
        self.connection.commit()

    def mark_worker_started(self, *, run_token: str, process_id: int) -> list[str]:
        """
        子プロセス起動後に実行権を確定し、対象パス群を返す。
        """
        runtime_row = self.connection.execute(
            """
            SELECT run_token
            FROM scheduler_runtime
            WHERE id = 1
            """
        ).fetchone()
        if runtime_row is None or str(runtime_row["run_token"] or "") != run_token:
            raise RuntimeError("Scheduler run token is invalid.")

        started_at = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET status = 'running',
                process_id = ?,
                last_started_at = ?,
                last_finished_at = NULL,
                last_error = NULL
            WHERE id = 1
            """,
            (process_id, started_at),
        )
        self.connection.commit()
        self.append_log(level="info", message="スケジューラー実行を開始しました。")
        rows = self.connection.execute(
            """
            SELECT folder_path
            FROM scheduler_paths
            WHERE scheduler_id = 1
            ORDER BY sort_order ASC
            """
        ).fetchall()
        return [str(row["folder_path"]) for row in rows]

    def set_current_path(self, folder_path: str | None) -> None:
        """
        現在処理中のフォルダを更新する。
        """
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET current_path = ?
            WHERE id = 1
            """,
            (folder_path,),
        )
        self.connection.commit()

    def finish_run(self, *, last_error: str | None = None) -> None:
        """
        実行完了後に待機状態へ戻し、次回は明示的な再開始を必要にする。
        """
        finished_at = datetime.now(UTC).isoformat()
        next_status = "failed" if last_error else "completed"
        self.connection.execute(
            """
            UPDATE scheduler_settings
            SET is_enabled = 0
            WHERE id = 1
            """
        )
        self.connection.execute(
            """
            UPDATE scheduler_runtime
            SET status = ?,
                current_path = NULL,
                process_id = NULL,
                run_token = NULL,
                last_finished_at = ?,
                last_error = ?
            WHERE id = 1
            """,
            (next_status, finished_at, last_error),
        )
        self.connection.commit()
        self.append_log(
            level="error" if last_error else "info",
            message="スケジューラー実行が失敗しました。" if last_error else "スケジューラー実行が完了しました。",
        )

    def run_scheduled_indexing(self, *, run_token: str) -> None:
        """
        別プロセス側で各フォルダを順次インデックスし、フォルダ単位でログを残す。
        """
        folder_paths = self.mark_worker_started(run_token=run_token, process_id=os.getpid())
        app_settings = IndexService(connection=self.connection).get_app_settings()
        index_service = IndexService(connection=self.connection)

        last_error: str | None = None
        for folder_path in folder_paths:
            self.set_current_path(folder_path)
            self.append_log(level="info", message="フォルダのインデックスを開始します。", folder_path=folder_path)
            try:
                # スケジューラーで指定したパスは実行時に検索対象へ有効追加してから処理する。
                index_service.set_search_target_enabled(folder_path=folder_path, is_enabled=True)
                index_service.ensure_fresh_target(
                    full_path=folder_path,
                    refresh_window_minutes=0,
                    exclude_keywords=app_settings.exclude_keywords,
                    index_depth=128,
                    types=app_settings.index_selected_extensions.replace("\n", " "),
                )
                self.append_log(level="info", message="フォルダのインデックスが完了しました。", folder_path=folder_path)
            except Exception as error:
                last_error = str(error)
                self.append_log(level="error", message=f"フォルダのインデックスに失敗しました: {error}", folder_path=folder_path)

        self.finish_run(last_error=last_error)

    def _normalize_scheduler_paths(self, paths: list[str]) -> list[str]:
        """
        スケジュール対象パスを絶対パス・重複排除済みの保存形式へ整える。
        """
        normalized_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in paths:
            if not str(raw_path).strip():
                continue
            try:
                normalized = normalize_path(raw_path).as_posix()
            except AbsolutePathRequiredError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Scheduler folder paths must be absolute paths or Windows UNC paths.",
                ) from error
            if normalized in seen:
                continue
            if not Path(normalized).exists() or not Path(normalized).is_dir():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Scheduler folder path must be an existing directory: {normalized}",
                )
            seen.add(normalized)
            normalized_paths.append(normalized)
        return normalized_paths


class SchedulerMonitor:
    """
    メインプロセス内で待機し、開始時刻になったら子プロセス起動だけを担当する。
    """

    def __init__(self, *, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="scheduler-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            connection = get_connection()
            try:
                initialize_schema(connection)
                SchedulerService(connection=connection).try_start_due_schedule()
            finally:
                connection.close()
            self._stop_event.wait(self.poll_interval_seconds)
