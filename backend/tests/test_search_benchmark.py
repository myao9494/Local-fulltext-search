"""
検索ベンチマーク用ユーティリティの件数計算を検証する。
"""

from app.services.search_benchmark import BenchmarkConfig, _build_folder_root, _count_global_hits, _count_target_hits


def test_benchmark_config_requires_even_folder_distribution() -> None:
    """
    ベンチマーク生成は folder_count へ均等配置できる件数だけを受け付ける。
    """
    config = BenchmarkConfig(total_files=12, folder_count=3)

    assert config.files_per_folder == 4


def test_build_folder_root_returns_stable_target_path() -> None:
    """
    ベンチマーク用フォルダパスはゼロ埋めで安定化する。
    """
    assert _build_folder_root(42) == "/benchmark/folder_000042"


def test_hit_counters_include_target_and_sparse_global_hits() -> None:
    """
    ヒット件数計算は対象フォルダヒットと全体ヒットの重複を二重計上しない。
    """
    config = BenchmarkConfig(
        total_files=12,
        folder_count=3,
        target_folder_index=1,
        target_hit_every=2,
        global_hit_every=5,
    )

    assert _count_target_hits(config) == 2
    assert _count_global_hits(config) == 5
