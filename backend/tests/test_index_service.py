"""
インデックスサービスの効率化テスト。
バッチcommit・ディレクトリ走査・除外キーワード最適化の動作を検証する。
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

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


def test_needs_refresh_when_japanese_bigram_segment_is_missing(tmp_path: Path) -> None:
    """
    旧インデックスに日本語 bi-gram 補助セグメントがない場合は再インデックスする。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    note_path = target / "sushi.md"
    note_path.write_text("今日はお寿司が食べたい。", encoding="utf-8")

    target_row = service._ensure_target(
        full_path=str(target),
        exclude_keywords="",
        index_depth=5,
        selected_extensions="",
    )
    indexed_at = datetime.now(UTC).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path, file_name, file_ext, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            note_path.as_posix(),
            note_path.as_posix(),
            note_path.name,
            note_path.suffix.lower(),
            note_path.stat().st_mtime,
            note_path.stat().st_size,
            indexed_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        (int(cursor.lastrowid), note_path.as_posix(), "今日はお寿司が食べたい。"),
    )
    service._mark_target_indexed(
        int(target_row["id"]),
        exclude_keywords="",
        index_depth=5,
        selected_extensions="",
    )

    refreshed_target = service._ensure_target(
        full_path=str(target),
        exclude_keywords="",
        index_depth=5,
        selected_extensions="",
    )
    assert service._needs_refresh(
        refreshed_target,
        refresh_window_minutes=60,
        exclude_keywords="",
        index_depth=5,
        selected_extensions="",
    )


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

    # file_segments と FTS からも削除されていること
    assert connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()["count"] == 1
    # FTS5 にゴーストレコードが残っていないこと
    fts_count = connection.execute("SELECT COUNT(*) AS count FROM file_segments_fts").fetchone()["count"]
    assert fts_count == 1


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


def test_index_records_failed_files_and_continues(tmp_path: Path) -> None:
    """
    取得失敗したファイルはログへ残しつつ、他のファイルのインデックス処理は継続する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    ok_file = target / "ok.md"
    ng_file = target / "ng.md"
    ok_file.write_text("searchable content", encoding="utf-8")
    ng_file.write_text("broken content", encoding="utf-8")

    original_extract_text = __import__("app.services.index_service", fromlist=["extract_text"]).extract_text

    def fake_extract_text(path: Path) -> str:
        if path == ng_file:
            raise OSError("simulated read failure")
        return original_extract_text(path)

    with patch("app.services.index_service.extract_text", side_effect=fake_extract_text):
        service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    failed_files = connection.execute(
        "SELECT normalized_path, file_name, error_message FROM failed_files ORDER BY file_name"
    ).fetchall()

    assert [row["file_name"] for row in indexed_files] == ["ok.md"]
    assert len(failed_files) == 1
    assert failed_files[0]["file_name"] == "ng.md"
    assert "simulated read failure" in failed_files[0]["error_message"]


def test_index_depth_limits_recursive_walk(tmp_path: Path) -> None:
    """
    index_depth に応じて走査深さを制限し、設定変更時は再インデックスされる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    nested = target / "nested"
    deep = nested / "deep"
    deep.mkdir(parents=True)
    (target / "root.md").write_text("root level", encoding="utf-8")
    (nested / "child.md").write_text("child level", encoding="utf-8")
    (deep / "grandchild.md").write_text("grandchild level", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, index_depth=0)

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert [row["file_name"] for row in indexed_files] == ["root.md"]

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, index_depth=1)

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert [row["file_name"] for row in indexed_files] == ["child.md", "root.md"]


def test_index_rejects_relative_full_path(tmp_path: Path) -> None:
    """
    インデックス対象 full_path は相対パスを受け付けず 400 系エラーにする。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)

    with patch.object(service, "_update_status"), patch.object(service, "_is_running", return_value=False):
        try:
            service.ensure_fresh_target(full_path="docs", refresh_window_minutes=0)
        except HTTPException as error:
            assert error.status_code == 400
            assert "absolute path" in str(error.detail).lower()
        else:
            raise AssertionError("HTTPException was not raised for relative full_path")


def test_reset_database_clears_indexed_files_targets_and_failures(tmp_path: Path) -> None:
    """
    DB 初期化を実行すると、インデックス済みデータと失敗履歴を空に戻し、ステータスも初期化する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "note.md").write_text("searchable memo", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)
    connection.execute(
        """
        INSERT INTO failed_files(normalized_path, file_name, error_message, last_failed_at)
        VALUES (?, ?, ?, ?)
        """,
        (str(target / "broken.md"), "broken.md", "sample error", datetime.now(UTC).isoformat()),
    )
    connection.commit()

    service.reset_database()

    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 0
    assert connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()["count"] == 0
    assert connection.execute("SELECT COUNT(*) AS count FROM targets").fetchone()["count"] == 0
    assert connection.execute("SELECT COUNT(*) AS count FROM failed_files").fetchone()["count"] == 0

    status = service.get_status()
    assert status.total_files == 0
    assert status.error_count == 0
    assert status.is_running is False
    assert status.last_started_at is None
    assert status.last_finished_at is None


def test_selected_types_limit_indexed_extensions_and_include_filename_only_files(tmp_path: Path) -> None:
    """
    対象拡張子で走査対象を絞り込み、画像のような本文なしファイルもファイル名検索用に登録する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "note.md").write_text("searchable memo", encoding="utf-8")
    (target / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, types=".png")

    indexed_files = connection.execute("SELECT file_name, file_ext FROM files ORDER BY file_name").fetchall()
    assert [(row["file_name"], row["file_ext"]) for row in indexed_files] == [("diagram.png", ".png")]
    assert connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()["count"] == 0

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, types=".md,.png")

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert [row["file_name"] for row in indexed_files] == ["diagram.png", "note.md"]
    assert connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()["count"] == 1


def test_root_path_range_query_handles_filesystem_root(tmp_path: Path) -> None:
    """
    範囲クエリ最適化後も、ルートディレクトリ配下の既存レコードを正しく取得・削除できる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)

    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path, file_name, file_ext, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/tmp/example.md", "/tmp/example.md", "example.md", ".md", 0.0, 10, "2026-04-13T00:00:00+00:00"),
    )
    connection.commit()

    loaded = service._load_existing_files("/")
    assert "/tmp/example.md" in loaded

    service._remove_deleted_files(set(), root_path="/")
    remaining = connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()
    assert remaining["count"] == 0


def _create_connection(tmp_path: Path) -> sqlite3.Connection:
    """
    テストごとの一時 SQLite 接続を作成する。
    """
    connection = sqlite3.connect(tmp_path / "test_index.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(connection)
    return connection
