"""
合成の大規模検索DBを生成し、対象フォルダ絞り込みあり/なしの検索速度を計測する CLI。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from app.services.search_benchmark import (
    BenchmarkConfig,
    create_benchmark_database,
    default_benchmark_path,
    format_summary,
    run_benchmark,
)


def main() -> int:
    """
    CLI 引数を解釈してベンチマーク生成と実測を実行する。
    """
    parser = argparse.ArgumentParser(description="Create and benchmark a large synthetic search database.")
    parser.add_argument("--db-path", type=Path, default=default_benchmark_path())
    parser.add_argument("--total-files", type=int, default=3_000_000)
    parser.add_argument("--folder-count", type=int, default=300)
    parser.add_argument("--target-folder-index", type=int, default=42)
    parser.add_argument("--query", type=str, default="needle")
    parser.add_argument("--target-hit-every", type=int, default=500)
    parser.add_argument("--global-hit-every", type=int, default=2_000)
    parser.add_argument("--batch-size", type=int, default=20_000)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--timed-runs", type=int, default=5)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    config = BenchmarkConfig(
        total_files=args.total_files,
        folder_count=args.folder_count,
        target_folder_index=args.target_folder_index,
        query=args.query,
        target_hit_every=args.target_hit_every,
        global_hit_every=args.global_hit_every,
        batch_size=args.batch_size,
        warmup_runs=args.warmup_runs,
        timed_runs=args.timed_runs,
        limit=args.limit,
    )

    generation_started = time.perf_counter()
    counts = create_benchmark_database(args.db_path, config)
    generation_seconds = time.perf_counter() - generation_started
    summary = run_benchmark(args.db_path, config)

    print(f"generation_seconds: {generation_seconds:.2f}")
    print(f"generated_file_count: {counts['file_count']}")
    print(f"generated_segment_count: {counts['segment_count']}")
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
