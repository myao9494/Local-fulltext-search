"""
スケジューラーサービスの保存・起動・ログ出力を検証する。
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import settings
from app.db.schema import initialize_schema
from app.services.scheduler_service import SchedulerService


def test_schedule_indexing_persists_paths_and_clears_previous_logs(tmp_path: Path) -> None:
    """
    スケジュール開始時は対象パスを保存し、以前のログを初期化して scheduled 状態へ切り替える。
    """
    connection = _create_connection(tmp_path)
    service = SchedulerService(connection=connection)
    target_a = tmp_path / "docs-a"
    target_b = tmp_path / "docs-b"
    target_a.mkdir()
    target_b.mkdir()
    service.append_log(level="info", message="old log")

    payload = service.schedule_indexing(
        paths=[str(target_a), str(target_b)],
        start_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    assert payload.paths == [target_a.as_posix(), target_b.as_posix()]
    assert payload.is_enabled is True
    assert payload.status == "scheduled"
    assert len(payload.logs) == 1
    assert "スケジュールを開始しました" in payload.logs[0].message


def test_try_start_due_schedule_launches_worker_process_once(tmp_path: Path) -> None:
    """
    開始時刻を過ぎた scheduled ジョブだけを 1 回だけ子プロセス起動する。
    """
    connection = _create_connection(tmp_path)
    service = SchedulerService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    service.schedule_indexing(paths=[str(target)], start_at=datetime.now(UTC) - timedelta(minutes=1))
    captured: dict[str, object] = {}

    class StubProcess:
        pid = 43210

    def fake_popen(command: list[str], cwd: str) -> StubProcess:
        captured["command"] = command
        captured["cwd"] = cwd
        return StubProcess()

    assert service.try_start_due_schedule(process_factory=fake_popen) is True
    assert service.try_start_due_schedule(process_factory=fake_popen) is False
    runtime_row = connection.execute("SELECT status, process_id, run_token FROM scheduler_runtime WHERE id = 1").fetchone()
    assert runtime_row["status"] == "launching"
    assert runtime_row["process_id"] == 43210
    assert runtime_row["run_token"] is not None
    assert captured["command"][2] == "app.services.scheduler_worker"


def test_run_scheduled_indexing_indexes_each_folder_and_writes_completion_logs(tmp_path: Path, monkeypatch) -> None:
    """
    子プロセス実行では対象フォルダを順次インデックスし、完了ログをフォルダ単位で残す。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "database_name", "scheduler.db")

    first = tmp_path / "docs-1"
    second = tmp_path / "docs-2"
    first.mkdir()
    second.mkdir()
    (first / "alpha.md").write_text("alpha content", encoding="utf-8")
    (second / "beta.md").write_text("beta content", encoding="utf-8")

    connection = sqlite3.connect(data_dir / "scheduler.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(connection)
    service = SchedulerService(connection=connection)
    service.schedule_indexing(paths=[str(first), str(second)], start_at=datetime.now(UTC) - timedelta(minutes=1))
    service.try_start_due_schedule(process_factory=lambda command, cwd: type("Proc", (), {"pid": 99999})())
    runtime_row = connection.execute("SELECT run_token FROM scheduler_runtime WHERE id = 1").fetchone()
    run_token = str(runtime_row["run_token"])
    connection.close()

    worker_connection = sqlite3.connect(data_dir / "scheduler.db")
    worker_connection.row_factory = sqlite3.Row
    worker_connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(worker_connection)
    SchedulerService(connection=worker_connection).run_scheduled_indexing(run_token=run_token)

    indexed_files = worker_connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()
    log_rows = worker_connection.execute(
        "SELECT message, folder_path FROM scheduler_logs WHERE folder_path IS NOT NULL ORDER BY id ASC"
    ).fetchall()
    runtime_row = worker_connection.execute("SELECT status, current_path FROM scheduler_runtime WHERE id = 1").fetchone()
    settings_row = worker_connection.execute("SELECT is_enabled FROM scheduler_settings WHERE id = 1").fetchone()

    assert indexed_files["count"] == 2
    assert [row["folder_path"] for row in log_rows if "完了" in row["message"]] == [first.as_posix(), second.as_posix()]
    assert runtime_row["status"] == "completed"
    assert runtime_row["current_path"] is None
    assert settings_row["is_enabled"] == 0


def test_windows_daily_schedule_launches_enabled_search_targets_at_fixed_time(tmp_path: Path, monkeypatch) -> None:
    """
    Windows では固定時刻に有効な検索対象フォルダを全階層インデックス対象として子プロセス起動する。
    """
    connection = _create_connection(tmp_path)
    first = tmp_path / "docs-a"
    second = tmp_path / "docs-b"
    first.mkdir()
    second.mkdir()
    service = SchedulerService(connection=connection)
    service.schedule_indexing(paths=[str(first)], start_at=datetime.now(UTC) + timedelta(days=1))
    connection.execute(
        """
        INSERT INTO targets(
            full_path, exclude_keywords, index_depth, selected_extensions,
            is_search_target_enabled, indexed_file_count, source_type, created_at, updated_at
        )
        VALUES (?, '', 3, '', 1, 0, 'local', ?, ?),
               (?, '', 3, '', 0, 0, 'local', ?, ?),
               ('https://example.com', '', 3, '', 1, 0, 'web', ?, ?)
        """,
        (
            first.as_posix(),
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            second.as_posix(),
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
        ),
    )
    connection.commit()
    monkeypatch.setattr("app.services.scheduler_service.platform.system", lambda: "Windows")
    captured: dict[str, object] = {}

    class StubProcess:
        pid = 24680

    def fake_popen(command: list[str], cwd: str) -> StubProcess:
        captured["command"] = command
        captured["cwd"] = cwd
        return StubProcess()

    started = service.try_start_due_windows_daily_schedule(
        now=datetime(2026, 5, 10, 10, 0),
        process_factory=fake_popen,
    )
    second_start = service.try_start_due_windows_daily_schedule(
        now=datetime(2026, 5, 10, 10, 0),
        process_factory=fake_popen,
    )

    path_rows = connection.execute("SELECT folder_path FROM scheduler_paths ORDER BY sort_order").fetchall()
    runtime_row = connection.execute("SELECT status, process_id FROM scheduler_runtime WHERE id = 1").fetchone()

    assert started is True
    assert second_start is False
    assert [row["folder_path"] for row in path_rows] == [first.as_posix()]
    assert runtime_row["status"] == "launching"
    assert runtime_row["process_id"] == 24680
    assert captured["command"][2] == "app.services.scheduler_worker"


def test_windows_daily_schedule_does_not_run_on_macos(tmp_path: Path, monkeypatch) -> None:
    """
    macOS では Windows 固定時刻スケジュールを起動しない。
    """
    connection = _create_connection(tmp_path)
    monkeypatch.setattr("app.services.scheduler_service.platform.system", lambda: "Darwin")

    assert (
        SchedulerService(connection=connection).try_start_due_windows_daily_schedule(
            now=datetime(2026, 5, 10, 10, 0),
            process_factory=lambda command, cwd: type("Proc", (), {"pid": 1})(),
        )
        is False
    )


def test_recover_interrupted_windows_run_clears_running_state(tmp_path: Path) -> None:
    """
    再起動後に残った実行中状態は再開せず、次の起動で一から取り直せる状態へ戻す。
    """
    connection = _create_connection(tmp_path)
    connection.execute("UPDATE index_runs SET is_running = 1, cancel_requested = 1 WHERE id = 1")
    connection.execute(
        """
        UPDATE scheduler_runtime
        SET status = 'running', current_path = '/tmp/docs', process_id = 123, run_token = 'old'
        WHERE id = 1
        """
    )
    connection.commit()

    recovered = SchedulerService(connection=connection).recover_interrupted_windows_run()

    index_row = connection.execute("SELECT is_running, cancel_requested FROM index_runs WHERE id = 1").fetchone()
    runtime_row = connection.execute("SELECT status, current_path, process_id, run_token FROM scheduler_runtime WHERE id = 1").fetchone()

    assert recovered is True
    assert index_row["is_running"] == 0
    assert index_row["cancel_requested"] == 0
    assert runtime_row["status"] == "interrupted"
    assert runtime_row["current_path"] is None
    assert runtime_row["process_id"] is None
    assert runtime_row["run_token"] is None


def _create_connection(tmp_path: Path) -> sqlite3.Connection:
    """
    テストごとの一時 SQLite 接続を作成する。
    """
    connection = sqlite3.connect(tmp_path / "test_scheduler.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(connection)
    return connection
