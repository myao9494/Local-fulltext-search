"""
大規模検索のベンチマーク用に、合成データベースの生成と検索計測をまとめて扱う。
300万件級でも再利用しやすいよう、生成条件と計測条件を dataclass で明示する。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import os
import sqlite3
import statistics
import time

from app.db.schema import initialize_schema
from app.models.indexing import AppSettingsResponse
from app.models.search import SearchQueryParams
from app.services.search_service import SearchService


@dataclass(frozen=True)
class BenchmarkConfig:
    """
    ベンチマーク用データセットの規模とヒット分布を定義する。
    """

    total_files: int = 3_000_000
    folder_count: int = 300
    target_folder_index: int = 42
    query: str = "needle"
    target_hit_every: int = 500
    global_hit_every: int = 2_000
    batch_size: int = 20_000
    warmup_runs: int = 1
    timed_runs: int = 5
    limit: int = 20

    @property
    def files_per_folder(self) -> int:
        """
        各フォルダへ均等配置するため、総件数は folder_count で割り切れる前提にする。
        """
        if self.total_files % self.folder_count != 0:
            raise ValueError("total_files must be divisible by folder_count for benchmark generation.")
        return self.total_files // self.folder_count

    @property
    def target_root(self) -> str:
        """
        ベンチマークで部分検索に使う対象フォルダを返す。
        """
        return _build_folder_root(self.target_folder_index)


@dataclass(frozen=True)
class BenchmarkSummary:
    """
    生成済みデータセットと検索実測の要約結果。
    """

    database_path: str
    file_count: int
    segment_count: int
    database_size_bytes: int
    target_root: str
    target_query: str
    target_hit_count: int
    global_hit_count: int
    scoped_search_seconds: list[float]
    global_search_seconds: list[float]
    scoped_total: int
    global_total: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _build_folder_root(folder_index: int) -> str:
    """
    合成データセット内のフォルダルートを安定した形式で返す。
    """
    return f"/benchmark/folder_{folder_index:06d}"


def _build_file_path(folder_index: int, file_index_in_folder: int) -> str:
    """
    1ファイルぶんの仮想フルパスを返す。
    """
    return f"{_build_folder_root(folder_index)}/sub_{file_index_in_folder // 1000:03d}/file_{file_index_in_folder:05d}.md"


def _is_target_hit(*, folder_index: int, file_index_in_folder: int, config: BenchmarkConfig) -> bool:
    """
    対象フォルダ内のヒット件数を一定間隔で発生させる。
    """
    return folder_index == config.target_folder_index and file_index_in_folder % config.target_hit_every == 0


def _is_global_hit(*, global_file_index: int, config: BenchmarkConfig) -> bool:
    """
    全体検索用のヒットをまばらに混ぜ、未絞り込み検索との差を測れるようにする。
    """
    return global_file_index % config.global_hit_every == 0


def create_benchmark_database(database_path: Path, config: BenchmarkConfig) -> dict[str, int]:
    """
    指定規模の検索ベンチマーク DB を生成し、件数情報を返す。
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    connection = sqlite3.connect(database_path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.execute("PRAGMA synchronous = OFF;")
        connection.execute("PRAGMA cache_size = -128000;")
        connection.execute("PRAGMA temp_store = MEMORY;")
        connection.execute("PRAGMA mmap_size = 268435456;")
        initialize_schema(connection)
        _drop_fts_triggers(connection)
        _bulk_insert_dataset(connection, config)
        connection.execute("INSERT INTO file_segments_fts(file_segments_fts) VALUES ('rebuild');")
        initialize_schema(connection)
        connection.execute("PRAGMA optimize;")
        connection.commit()

        file_count = int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        segment_count = int(connection.execute("SELECT COUNT(*) FROM file_segments").fetchone()[0])
        return {
            "file_count": file_count,
            "segment_count": segment_count,
            "target_hit_count": _count_target_hits(config),
            "global_hit_count": _count_global_hits(config),
        }
    finally:
        connection.close()


def run_benchmark(database_path: Path, config: BenchmarkConfig) -> BenchmarkSummary:
    """
    生成済み DB に対して対象フォルダ付き検索と全体検索の実測を行う。
    """
    connection = sqlite3.connect(database_path, check_same_thread=False, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.execute("PRAGMA synchronous = NORMAL;")
        connection.execute("PRAGMA cache_size = -128000;")
        connection.execute("PRAGMA temp_store = MEMORY;")
        connection.execute("PRAGMA mmap_size = 268435456;")

        service = SearchService(connection=connection)
        service.index_service.get_app_settings = lambda: AppSettingsResponse(
            exclude_keywords="",
            synonym_groups="",
            index_selected_extensions=".md",
            custom_content_extensions="",
            custom_filename_extensions="",
        )

        scoped_params = SearchQueryParams(
            q=config.query,
            full_path=config.target_root,
            search_all_enabled=True,
            index_depth=5,
            refresh_window_minutes=0,
            limit=config.limit,
        )
        global_params = SearchQueryParams(
            q=config.query,
            full_path="",
            search_all_enabled=True,
            index_depth=5,
            refresh_window_minutes=0,
            limit=config.limit,
        )

        for _ in range(config.warmup_runs):
            service.search(scoped_params)
            service.search(global_params)

        scoped_result, scoped_times = _time_search(service, scoped_params, config.timed_runs)
        global_result, global_times = _time_search(service, global_params, config.timed_runs)
        return BenchmarkSummary(
            database_path=str(database_path),
            file_count=int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
            segment_count=int(connection.execute("SELECT COUNT(*) FROM file_segments").fetchone()[0]),
            database_size_bytes=database_path.stat().st_size,
            target_root=config.target_root,
            target_query=config.query,
            target_hit_count=_count_target_hits(config),
            global_hit_count=_count_global_hits(config),
            scoped_search_seconds=scoped_times,
            global_search_seconds=global_times,
            scoped_total=scoped_result.total,
            global_total=global_result.total,
        )
    finally:
        connection.close()


def format_summary(summary: BenchmarkSummary) -> str:
    """
    CLI 表示向けに、実測結果を読みやすいテキストへ整形する。
    """
    scoped_median = statistics.median(summary.scoped_search_seconds)
    global_median = statistics.median(summary.global_search_seconds)
    return "\n".join(
        [
            f"database: {summary.database_path}",
            f"db_size_mb: {summary.database_size_bytes / 1024 / 1024:.2f}",
            f"files: {summary.file_count}",
            f"segments: {summary.segment_count}",
            f"target_root: {summary.target_root}",
            f"query: {summary.target_query}",
            f"target_hit_count: {summary.target_hit_count}",
            f"global_hit_count: {summary.global_hit_count}",
            f"scoped_total: {summary.scoped_total}",
            f"global_total: {summary.global_total}",
            f"scoped_times_s: {', '.join(f'{value:.4f}' for value in summary.scoped_search_seconds)}",
            f"global_times_s: {', '.join(f'{value:.4f}' for value in summary.global_search_seconds)}",
            f"scoped_median_s: {scoped_median:.4f}",
            f"global_median_s: {global_median:.4f}",
            f"speedup_vs_global: {global_median / scoped_median:.2f}x" if scoped_median > 0 else "speedup_vs_global: inf",
        ]
    )


def _time_search(service: SearchService, params: SearchQueryParams, run_count: int):
    """
    同じ検索を複数回実行し、経過秒を収集する。
    """
    result = None
    elapsed_seconds: list[float] = []
    for _ in range(run_count):
        started_at = time.perf_counter()
        result = service.search(params)
        elapsed_seconds.append(time.perf_counter() - started_at)
    return result, elapsed_seconds


def _drop_fts_triggers(connection: sqlite3.Connection) -> None:
    """
    一括投入中は FTS トリガーを止め、最後に rebuild でまとめて反映する。
    """
    connection.execute("DROP TRIGGER IF EXISTS file_segments_ai;")
    connection.execute("DROP TRIGGER IF EXISTS file_segments_ad;")
    connection.execute("DROP TRIGGER IF EXISTS file_segments_au;")
    connection.commit()


def _bulk_insert_dataset(connection: sqlite3.Connection, config: BenchmarkConfig) -> None:
    """
    files / file_segments をバッチで投入する。
    """
    indexed_at = datetime.now(UTC).isoformat()
    created_at = datetime(2026, 4, 19, tzinfo=UTC).timestamp()
    folder_file_count = config.files_per_folder
    next_file_id = 1

    for folder_index in range(config.folder_count):
        folder_started = folder_index * folder_file_count
        for batch_start in range(0, folder_file_count, config.batch_size):
            files_rows: list[tuple[object, ...]] = []
            segment_rows: list[tuple[object, ...]] = []
            batch_end = min(batch_start + config.batch_size, folder_file_count)
            for file_index_in_folder in range(batch_start, batch_end):
                global_file_index = folder_started + file_index_in_folder
                full_path = _build_file_path(folder_index, file_index_in_folder)
                file_name = Path(full_path).name
                is_hit = _is_target_hit(
                    folder_index=folder_index,
                    file_index_in_folder=file_index_in_folder,
                    config=config,
                ) or _is_global_hit(global_file_index=global_file_index, config=config)
                body = (
                    f"alpha {config.query} benchmark document {next_file_id}"
                    if is_hit
                    else f"alpha benchmark document {next_file_id}"
                )
                files_rows.append(
                    (
                        next_file_id,
                        full_path,
                        full_path,
                        file_name,
                        ".md",
                        created_at,
                        created_at,
                        len(body),
                        indexed_at,
                        None,
                        0,
                    )
                )
                segment_rows.append((next_file_id, "body", full_path, body))
                next_file_id += 1

            connection.executemany(
                """
                INSERT INTO files(
                    id, full_path, normalized_path, file_name, file_ext,
                    created_at, mtime, size, indexed_at, last_error, click_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                files_rows,
            )
            connection.executemany(
                """
                INSERT INTO file_segments(file_id, segment_type, segment_label, content)
                VALUES (?, ?, ?, ?)
                """,
                segment_rows,
            )
            connection.commit()


def _count_target_hits(config: BenchmarkConfig) -> int:
    """
    対象フォルダ配下でヒットする件数を返す。
    """
    return (config.files_per_folder - 1) // config.target_hit_every + 1


def _count_global_hits(config: BenchmarkConfig) -> int:
    """
    全体検索でヒットする件数を返す。
    対象フォルダ内のヒットと重複する global hit は 1 件として数える。
    """
    hit_count = 0
    for folder_index in range(config.folder_count):
        for file_index_in_folder in range(config.files_per_folder):
            global_file_index = folder_index * config.files_per_folder + file_index_in_folder
            if _is_target_hit(folder_index=folder_index, file_index_in_folder=file_index_in_folder, config=config):
                hit_count += 1
                continue
            if _is_global_hit(global_file_index=global_file_index, config=config):
                hit_count += 1
    return hit_count


def default_benchmark_path() -> Path:
    """
    ベンチマーク DB の既定保存先を返す。
    """
    return Path(os.getenv("SEARCH_APP_BENCHMARK_DB", "/tmp/local_fulltext_search_benchmark_3m.db")).resolve()
