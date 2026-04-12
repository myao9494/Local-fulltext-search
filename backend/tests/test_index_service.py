"""
インデックスサービスの効率化テスト。
バッチcommit・ディレクトリ走査・除外キーワード最適化の動作を検証する。
"""

import sqlite3
from pathlib import Path

from app.db.schema import initialize_schema
from app.services.index_service import IndexService


def test_batch_commit_indexes_multiple_files_correctly(tmp_path: Path) -> None:
    """
    複数ファイルをインデックスした場合、全ファイルがDBに正しく登録される。
    （バッチcommitに変更しても結果が変わらないことを保証する）
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()

    # 120ファイルを作成（バッチサイズ100を超える数）
    for i in range(120):
        (target / f"file_{i:03d}.md").write_text(f"content of file {i}", encoding="utf-8")

    service.ensure_fresh_target(
        full_path=str(target),
        refresh_window_minutes=60,
    )

    row = connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()
    assert row["count"] == 120

    # file_segmentsにも全件登録されていること
    seg_row = connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()
    assert seg_row["count"] == 120

    # FTSにも全件登録されていること
    fts_row = connection.execute("SELECT COUNT(*) AS count FROM file_segments_fts").fetchone()
    assert fts_row["count"] == 120


def test_unchanged_files_are_skipped_on_reindex(tmp_path: Path) -> None:
    """
    変更がないファイルは再インデックス対象外になる（mtime + sizeチェック）。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "stable.md").write_text("unchanged content", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    # 初回: indexed_at を取得
    row = connection.execute("SELECT indexed_at FROM files WHERE file_name = 'stable.md'").fetchone()
    first_indexed_at = row["indexed_at"]

    # 再インデックス（refresh_window_minutes=0 で強制実行）
    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    # indexed_at が変わっていないことで、スキップされたことを確認
    row = connection.execute("SELECT indexed_at FROM files WHERE file_name = 'stable.md'").fetchone()
    assert row["indexed_at"] == first_indexed_at


def test_deleted_files_are_removed_from_index(tmp_path: Path) -> None:
    """
    実ファイルが削除された場合、インデックスからも削除される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    file_a = target / "keep.md"
    file_b = target / "remove.md"
    file_a.write_text("keep this", encoding="utf-8")
    file_b.write_text("remove this", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)
    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 2

    # ファイルを削除して再インデックス
    file_b.unlink()
    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 1
    remaining = connection.execute("SELECT file_name FROM files").fetchone()
    assert remaining["file_name"] == "keep.md"

    # file_segments と FTS からも削除されていること（カスケード削除）
    assert connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()["count"] == 1


def test_exclude_keywords_skip_directories(tmp_path: Path) -> None:
    """
    除外キーワードに一致するディレクトリ配下のファイルはインデックスされない。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "project"
    target.mkdir()

    (target / "readme.md").write_text("project readme", encoding="utf-8")
    node_modules = target / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.md").write_text("should be excluded", encoding="utf-8")
    git_dir = target / ".git"
    git_dir.mkdir()
    (git_dir / "config.txt").write_text("git config", encoding="utf-8")

    service.ensure_fresh_target(
        full_path=str(target),
        refresh_window_minutes=0,
        exclude_keywords="node_modules\n.git",
    )

    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 1
    remaining = connection.execute("SELECT file_name FROM files").fetchone()
    assert remaining["file_name"] == "readme.md"


def test_exclude_keywords_skip_matching_file_names(tmp_path: Path) -> None:
    """
    除外キーワードに一致するファイル名もインデックス対象外になる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "project"
    target.mkdir()

    (target / "readme.md").write_text("project readme", encoding="utf-8")
    (target / "draft.md").write_text("should be excluded", encoding="utf-8")

    service.ensure_fresh_target(
        full_path=str(target),
        refresh_window_minutes=0,
        exclude_keywords="draft",
    )

    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 1
    remaining = connection.execute("SELECT file_name FROM files").fetchone()
    assert remaining["file_name"] == "readme.md"


def test_index_status_reflects_file_count(tmp_path: Path) -> None:
    """
    インデックス完了後、ステータスにファイル数が正しく反映される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    for i in range(5):
        (target / f"doc_{i}.md").write_text(f"document {i}", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    status = service.get_status()
    assert status.total_files == 5
    assert status.error_count == 0
    assert status.is_running is False


def _create_connection(tmp_path: Path) -> sqlite3.Connection:
    """
    テストごとの一時 SQLite 接続を作成する。
    """
    connection = sqlite3.connect(tmp_path / "test_index.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(connection)
    return connection
