"""
インデックスサービスの効率化テスト。
バッチcommit・ディレクトリ走査・除外キーワード最適化の動作を検証する。
"""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.db.schema import initialize_schema
from app.services.index_service import IndexingCancelledError, IndexService


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


def test_indexing_emits_phase_timing_logs(tmp_path: Path, caplog) -> None:
    """
    インデックス作成時はボトルネック確認用に主要フェーズの処理時間をログへ出す。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "body.md").write_text("alpha body", encoding="utf-8")
    (target / "image.png").write_bytes(b"image")

    with caplog.at_level(logging.INFO, logger="app.services.index_service"):
        service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    messages = [record.getMessage() for record in caplog.records]
    assert any("Index: existing metadata load time" in message for message in messages)
    assert any("Index: scan/dispatch time" in message for message in messages)
    assert any("Index: extraction wait time" in message for message in messages)
    assert any("Index: DB write time" in message for message in messages)
    assert any("Index: cleanup time" in message for message in messages)
    assert any("Index: total time" in message for message in messages)


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


def test_needs_refresh_when_target_index_version_is_missing_for_japanese_bigram_support(tmp_path: Path) -> None:
    """
    旧インデックス由来で target の索引バージョンが古い場合は再インデックスする。
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
            full_path, normalized_path, file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            note_path.as_posix(),
            note_path.as_posix(),
            note_path.name,
            note_path.suffix.lower(),
            note_path.stat().st_ctime,
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
        indexed_file_count=1,
    )
    connection.execute("UPDATE targets SET index_version = 0 WHERE id = ?", (int(target_row["id"]),))
    connection.commit()

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


def test_no_refresh_path_skips_status_update_and_recount(tmp_path: Path) -> None:
    """
    期限内で再インデックス不要なら、実行状態更新や件数再集計を行わず即座に復帰する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "stable.md").write_text("unchanged content", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=60)
    first_status = service.get_status()

    def fail_update_status(**_: object) -> None:
        raise AssertionError("_update_status should not run when refresh is unnecessary")

    service._update_status = fail_update_status

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=60)

    second_status = IndexService(connection=connection).get_status()
    assert second_status.last_started_at == first_status.last_started_at
    assert second_status.last_finished_at == first_status.last_finished_at
    assert second_status.total_files == 1


def test_app_settings_persist_obsidian_sidebar_explorer_data_path(tmp_path: Path) -> None:
    """
    Obsidian sidebar-explorer の data.json パスはアプリ共有設定として保存・再読込できる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)

    saved = service.update_app_settings(
        obsidian_sidebar_explorer_data_path="/Users/example/Vault/.obsidian/plugins/obsidian-sidebar-explorer/data.json"
    )

    assert (
        saved.obsidian_sidebar_explorer_data_path
        == "/Users/example/Vault/.obsidian/plugins/obsidian-sidebar-explorer/data.json"
    )
    reloaded = IndexService(connection=connection).get_app_settings()
    assert (
        reloaded.obsidian_sidebar_explorer_data_path
        == "/Users/example/Vault/.obsidian/plugins/obsidian-sidebar-explorer/data.json"
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


def test_json_family_files_store_only_json_values_in_index(tmp_path: Path) -> None:
    """
    JSON / Excalidraw / draw.io 系ファイルは、インデックスへ JSON の値だけを保存する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()

    (target / "settings.json").write_text(
        '{"title":"alpha","enabled":true,"items":[1,"beta"]}',
        encoding="utf-8",
    )
    (target / "board.excalidraw").write_text(
        '{"type":"excalidraw","elements":[{"text":"gamma note"}]}',
        encoding="utf-8",
    )
    (target / "flow.dio.svg").write_text(
        '<svg><metadata>{&quot;label&quot;:&quot;delta flow&quot;}</metadata><text>ignored text</text></svg>',
        encoding="utf-8",
    )

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    rows = connection.execute(
        """
        SELECT files.file_name, file_segments.content
        FROM file_segments
        INNER JOIN files ON files.id = file_segments.file_id
        WHERE file_segments.segment_type = 'body'
        ORDER BY files.file_name
        """
    ).fetchall()
    indexed_content = {row["file_name"]: row["content"] for row in rows}

    assert '"title"' not in indexed_content["settings.json"]
    assert "alpha" in indexed_content["settings.json"]
    assert "beta" in indexed_content["settings.json"]
    assert '"type"' not in indexed_content["board.excalidraw"]
    assert "gamma note" in indexed_content["board.excalidraw"]
    assert "<svg>" not in indexed_content["flow.dio.svg"]
    assert "delta flow" in indexed_content["flow.dio.svg"]
    assert "ignored text" not in indexed_content["flow.dio.svg"]


def test_xml_files_store_only_text_content_in_index(tmp_path: Path) -> None:
    """
    XML ファイルは、タグや属性ではなくテキストノードの中身だけをインデックスへ保存する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()

    (target / "layout.xml").write_text(
        "<root><title>alpha layout</title><item status='draft'>beta note</item></root>",
        encoding="utf-8",
    )

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    row = connection.execute(
        """
        SELECT file_segments.content
        FROM file_segments
        INNER JOIN files ON files.id = file_segments.file_id
        WHERE files.file_name = 'layout.xml' AND file_segments.segment_type = 'body'
        """
    ).fetchone()

    assert row is not None
    assert "alpha layout" in row["content"]
    assert "beta note" in row["content"]
    assert "<root>" not in row["content"]
    assert "status" not in row["content"]


def test_custom_extensions_can_be_indexed_by_content_or_filename_only(tmp_path: Path, monkeypatch) -> None:
    """
    利用者追加の拡張子は、本文抽出対象とファイル名のみ対象を分けてインデックスできる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "index_selected_extensions_name", "index_selected_extensions.txt")
    monkeypatch.setattr(settings, "custom_content_extensions_name", "custom_content_extensions.txt")
    monkeypatch.setattr(settings, "custom_filename_extensions_name", "custom_filename_extensions.txt")

    service.update_app_settings(
        index_selected_extensions=".dat\n.cae",
        custom_content_extensions=".dat",
        custom_filename_extensions=".cae",
    )

    target = tmp_path / "docs"
    target.mkdir()
    (target / "solver.dat").write_text("stress result alpha", encoding="utf-8")
    (target / "mesh.cae").write_text("binary-like payload", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, types=".dat .cae")

    rows = connection.execute(
        """
        SELECT files.file_name, file_segments.content
        FROM files
        LEFT JOIN file_segments
          ON file_segments.file_id = files.id
         AND file_segments.segment_type = 'body'
        ORDER BY files.file_name
        """
    ).fetchall()
    indexed_content = {row["file_name"]: row["content"] for row in rows}

    assert indexed_content["solver.dat"] == "stress result alpha"
    assert indexed_content["mesh.cae"] is None


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


def test_exclude_keywords_skip_relative_nested_directory_path(tmp_path: Path) -> None:
    """
    除外キーワードに相対ディレクトリパスを指定した場合、その配下だけを除外する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "project"
    target.mkdir()

    keep_dir = target / "Agent_SkillsX" / ".roo"
    keep_dir.mkdir(parents=True)
    (keep_dir / "keep.md").write_text("should stay indexed", encoding="utf-8")

    excluded_dir = target / "Agent_Skills" / ".roo"
    excluded_dir.mkdir(parents=True)
    (excluded_dir / "secret.md").write_text("should be excluded", encoding="utf-8")

    service.ensure_fresh_target(
        full_path=str(target),
        refresh_window_minutes=0,
        exclude_keywords="Agent_Skills/.roo",
        index_depth=3,
    )

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert [row["file_name"] for row in indexed_files] == ["keep.md"]


def test_exclude_keywords_treat_case_distinct_relative_directory_paths_separately(tmp_path: Path) -> None:
    """
    相対ディレクトリパス形式の除外キーワードは大文字小文字違いを別パスとして扱う。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    assert service._should_exclude_path(
        Path("/workspace/Agent_Skills/.roo/upper.md"),
        ["Agent_Skills/.roo"],
    ) is True
    assert service._should_exclude_path(
        Path("/workspace/agent_skills/.roo/lower.md"),
        ["Agent_Skills/.roo"],
    ) is False


def test_exclude_keywords_skip_dot_prefixed_children_under_relative_directory_prefix(tmp_path: Path) -> None:
    """
    `Agent_Skills/.` は Agent_Skills 配下のドット始まりディレクトリ/ファイルをまとめて除外する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "project"
    target.mkdir()

    excluded_dir = target / "Agent_Skills" / ".clinerules" / "workflows"
    excluded_dir.mkdir(parents=True)
    (excluded_dir / "secret.md").write_text("should be excluded", encoding="utf-8")

    keep_dir = target / "Agent_SkillsX" / ".clinerules" / "workflows"
    keep_dir.mkdir(parents=True)
    (keep_dir / "keep.md").write_text("should stay indexed", encoding="utf-8")

    service.ensure_fresh_target(
        full_path=str(target),
        refresh_window_minutes=0,
        exclude_keywords="Agent_Skills/.",
        index_depth=4,
    )

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert [row["file_name"] for row in indexed_files] == ["keep.md"]


def test_index_stores_compound_extension_distinctly_from_md(tmp_path: Path) -> None:
    """
    `.excalidraw.md` は `.md` と区別した file_ext で保存する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "memo.md").write_text("plain markdown", encoding="utf-8")
    (target / "board.excalidraw.md").write_text("diagram markdown", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute("SELECT file_name, file_ext FROM files ORDER BY file_name").fetchall()
    assert [(row["file_name"], row["file_ext"]) for row in indexed_files] == [
        ("board.excalidraw.md", ".excalidraw.md"),
        ("memo.md", ".md"),
    ]


def test_index_stores_dio_svg_distinctly_from_svg(tmp_path: Path) -> None:
    """
    `.dio.svg` は `.svg` と区別した file_ext で保存する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "icon.svg").write_bytes(b"<svg/>")
    (target / "flow.dio.svg").write_text("<svg><text>diagram</text></svg>", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute("SELECT file_name, file_ext FROM files ORDER BY file_name").fetchall()
    assert [(row["file_name"], row["file_ext"]) for row in indexed_files] == [
        ("flow.dio.svg", ".dio.svg"),
        ("icon.svg", ".svg"),
    ]


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
    assert status.cancel_requested is False


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

    def fake_extract_text(path: Path, *args, **kwargs) -> str:
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


def test_index_keeps_encrypted_pdf_as_filename_only_record(tmp_path: Path) -> None:
    """
    暗号化 PDF は失敗扱いにせず、本文なしのファイル名インデックスとして保持する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    pdf_file = target / "secret.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    with patch("app.services.index_service.extract_text", return_value=""):
        service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute(
        "SELECT file_name, file_ext, last_error FROM files ORDER BY file_name"
    ).fetchall()
    segments = connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()
    failed_files = connection.execute("SELECT COUNT(*) AS count FROM failed_files").fetchone()

    assert [(row["file_name"], row["file_ext"], row["last_error"]) for row in indexed_files] == [
        ("secret.pdf", ".pdf", None)
    ]
    assert segments["count"] == 0
    assert failed_files["count"] == 0


def test_index_records_audio_files_as_filename_only_entries(tmp_path: Path) -> None:
    """
    音声ファイルは本文抽出せず、ファイル名検索専用のレコードとして登録する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "music"
    target.mkdir()
    audio_file = target / "favorite-song.mp3"
    audio_file.write_bytes(b"ID3")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute(
        "SELECT file_name, file_ext, last_error FROM files ORDER BY file_name"
    ).fetchall()
    segments = connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()
    failed_files = connection.execute("SELECT COUNT(*) AS count FROM failed_files").fetchone()

    assert [(row["file_name"], row["file_ext"], row["last_error"]) for row in indexed_files] == [
        ("favorite-song.mp3", ".mp3", None)
    ]
    assert segments["count"] == 0
    assert failed_files["count"] == 0


def test_cancel_requested_during_indexing_stops_run_and_clears_running_state(tmp_path: Path) -> None:
    """
    実行中にキャンセル要求が入った場合、以降の走査を止めて is_running を解除する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    first = target / "first.md"
    second = target / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    def fake_walk_files(*args, **kwargs):
        yield first
        service.cancel_indexing()
        yield second

    with patch.object(service, "_walk_files", side_effect=fake_walk_files):
        try:
            service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)
        except HTTPException as error:
            assert error.status_code == 409
            assert error.detail == "Indexing was cancelled."
        else:
            raise AssertionError("HTTPException was not raised after cancellation")

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    assert "second.md" not in [row["file_name"] for row in indexed_files]

    status = service.get_status()
    assert status.is_running is False
    assert status.total_files <= 1
    assert status.error_count == 0
    assert status.cancel_requested is False
    assert status.last_error is None


def test_cancel_indexing_marks_status_as_cancel_requested(tmp_path: Path) -> None:
    """
    実行中フラグが立っている間に中止要求すると、ステータスに中止要求中が反映される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)

    service._update_status(is_running=True, cancel_requested=False)
    service.cancel_indexing()

    status = service.get_status()
    assert status.is_running is True
    assert status.cancel_requested is True


def test_cancel_requested_from_another_connection_stops_indexing(tmp_path: Path) -> None:
    """
    別プロセス・別リクエスト相当の接続で立てたキャンセル要求もインデックス処理が検知する。
    """
    first_connection = _create_connection(tmp_path)
    second_connection = _create_connection(tmp_path)
    service = IndexService(connection=first_connection)
    service._update_status(is_running=True, cancel_requested=False)
    second_connection.execute("UPDATE index_runs SET cancel_requested = 1 WHERE id = 1")
    second_connection.commit()

    try:
        service._raise_if_cancel_requested(service._get_run_controller())
    except IndexingCancelledError:
        pass
    else:
        raise AssertionError("IndexingCancelledError was not raised")


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


def test_list_indexed_targets_returns_all_indexed_folders_from_files(tmp_path: Path) -> None:
    """
    インデックス済みフォルダ一覧は files から祖先フォルダを展開して返し、件数は直下ファイル数を返す。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "alpha"
    nested = target / "nested"
    nested_child = nested / "child"
    nested.mkdir(parents=True)
    nested_child.mkdir()
    (target / "root.md").write_text("alpha", encoding="utf-8")
    (nested / "child.md").write_text("beta", encoding="utf-8")
    (nested_child / "leaf.md").write_text("gamma", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0, index_depth=3, types=".md")

    targets = service.list_indexed_targets().items

    folder_paths = [item.full_path for item in targets]
    assert target.as_posix() in folder_paths
    assert nested.as_posix() in folder_paths
    assert nested_child.as_posix() in folder_paths
    assert tmp_path.as_posix() not in folder_paths
    root_item = next(item for item in targets if item.full_path == target.as_posix())
    nested_item = next(item for item in targets if item.full_path == nested.as_posix())
    nested_child_item = next(item for item in targets if item.full_path == nested_child.as_posix())
    assert nested_item.indexed_file_count == 1
    assert nested_child_item.indexed_file_count == 1
    assert root_item.indexed_file_count == 1
    assert root_item.last_indexed_at is not None
    assert nested_item.last_indexed_at is not None


def test_delete_indexed_folders_removes_selected_folder_indexes_and_marks_targets_stale(tmp_path: Path) -> None:
    """
    選択したフォルダ配下の files・segments を削除し、重なる targets は再取得対象へ戻す。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    root = tmp_path / "root"
    keep = root / "keep"
    drop = root / "drop"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    (keep / "a.md").write_text("keep", encoding="utf-8")
    (drop / "b.md").write_text("drop", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(root), refresh_window_minutes=0, index_depth=2)

    deleted_count = service.delete_indexed_folders([drop.as_posix()]).deleted_count

    assert deleted_count == 1
    remaining_targets = connection.execute(
        "SELECT full_path, last_indexed_at, indexed_file_count FROM targets ORDER BY full_path"
    ).fetchall()
    remaining_files = connection.execute("SELECT normalized_path FROM files ORDER BY normalized_path").fetchall()
    remaining_segments = connection.execute("SELECT COUNT(*) AS count FROM file_segments").fetchone()

    assert [row["normalized_path"] for row in remaining_files] == [(keep / "a.md").as_posix()]
    assert remaining_segments["count"] == 1
    assert [row["full_path"] for row in remaining_targets] == [root.as_posix()]
    assert remaining_targets[0]["last_indexed_at"] is None
    assert remaining_targets[0]["indexed_file_count"] == 0


def test_list_search_targets_returns_targets_with_enabled_flag(tmp_path: Path) -> None:
    """
    検索対象フォルダ一覧には、有効フラグ・最終取得日時・ファイル件数を含める。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "memo.md").write_text("hello", encoding="utf-8")
    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    service.set_search_target_enabled(folder_path=target.as_posix(), is_enabled=False)

    items = service.list_search_targets().items
    assert len(items) == 1
    assert items[0].full_path == target.as_posix()
    assert items[0].is_enabled is False
    assert items[0].indexed_file_count == 1
    assert items[0].last_indexed_at is not None


def test_delete_search_targets_removes_target_only(tmp_path: Path) -> None:
    """
    検索対象フォルダの削除は targets のみ外し、既存インデックスデータは保持する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    target.mkdir()
    (target / "memo.md").write_text("hello", encoding="utf-8")
    service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    response = service.delete_search_targets([target.as_posix()])

    assert response.deleted_count == 1
    assert connection.execute("SELECT COUNT(*) AS count FROM targets").fetchone()["count"] == 0
    assert connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"] == 1


def test_ensure_fresh_target_rejects_path_outside_enabled_search_targets(tmp_path: Path) -> None:
    """
    検索対象フォルダが1件以上ある場合、対象外パスのインデックス作成は拒否する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    (allowed / "a.md").write_text("a", encoding="utf-8")
    (denied / "b.md").write_text("b", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(allowed), refresh_window_minutes=0)
    service.set_search_target_enabled(folder_path=allowed.as_posix(), is_enabled=True)

    with patch.object(service, "_is_running", return_value=False):
        try:
            service.ensure_fresh_target(full_path=str(denied), refresh_window_minutes=0)
        except HTTPException as error:
            assert error.status_code == 400
            assert "search target" in str(error.detail).lower()
        else:
            raise AssertionError("HTTPException was not raised for disabled search target path")


def test_ensure_fresh_target_uses_registered_parent_target_without_creating_child_target(tmp_path: Path) -> None:
    """
    親フォルダが検索対象にある場合、子フォルダで再インデックスしても targets に子を追加しない。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    parent = tmp_path / "workspace"
    child = parent / "team" / "backup"
    child.mkdir(parents=True)
    (child / "memo.md").write_text("hello", encoding="utf-8")

    service.ensure_fresh_target(full_path=str(parent), refresh_window_minutes=0)
    service.ensure_fresh_target(full_path=str(child), refresh_window_minutes=0)

    target_paths = connection.execute("SELECT full_path FROM targets ORDER BY full_path").fetchall()
    assert [str(row["full_path"]) for row in target_paths] == [parent.as_posix()]


def test_get_search_target_coverage_returns_parent_for_descendant(tmp_path: Path) -> None:
    """
    子フォルダ指定でも、有効な親検索対象があればカバー済みとして親パスを返す。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    parent = tmp_path / "workspace"
    child = parent / "team" / "backup"
    child.mkdir(parents=True)
    (child / "memo.md").write_text("hello", encoding="utf-8")
    service.ensure_fresh_target(full_path=str(parent), refresh_window_minutes=0)

    coverage = service.get_search_target_coverage(folder_path=str(child))

    assert coverage.is_covered is True
    assert coverage.covering_path == parent.as_posix()
    assert coverage.normalized_path == child.as_posix()


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


def test_network_error_path_is_added_to_exclude_keywords_and_skipped_on_retry(tmp_path: Path) -> None:
    """
    WinError 59 が出たディレクトリは除外キーワードへ追加し、次回以降の再走査対象から外す。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    target = tmp_path / "docs"
    restricted = target / "restricted"
    target.mkdir()
    restricted.mkdir()
    (target / "ok.md").write_text("searchable", encoding="utf-8")
    (restricted / "secret.md").write_text("do not touch", encoding="utf-8")

    original_scandir = __import__("app.services.index_service", fromlist=["os"]).os.scandir
    restricted_hits = 0

    def fake_scandir(path: str | bytes | int | Path):
        nonlocal restricted_hits
        if Path(path).name == "restricted":
            restricted_hits += 1
            error = OSError("[WinError 59] 予期しないネットワーク エラーが発生しました。")
            error.winerror = 59
            raise error
        return original_scandir(path)

    with patch("app.services.index_service.os.scandir", side_effect=fake_scandir):
        service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)
        service.ensure_fresh_target(full_path=str(target), refresh_window_minutes=0)

    indexed_files = connection.execute("SELECT file_name FROM files ORDER BY file_name").fetchall()
    target_row = connection.execute("SELECT exclude_keywords FROM targets").fetchone()

    assert [row["file_name"] for row in indexed_files] == ["ok.md"]
    assert restricted_hits == 1
    assert restricted.as_posix() in str(target_row["exclude_keywords"]).splitlines()


def test_app_settings_can_store_exclude_keywords(tmp_path: Path, monkeypatch) -> None:
    """
    アプリ設定として保存した除外キーワードはテキストファイルへ正規化して保持される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    exclude_keywords_path = tmp_path / "exclude_keywords.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "exclude_keywords_name", "exclude_keywords.txt")

    saved_settings = service.update_app_settings(exclude_keywords="dist\n\n build \n.dist\nbuild")

    assert saved_settings.exclude_keywords == "dist\nbuild\n.dist"
    assert exclude_keywords_path.read_text(encoding="utf-8") == "dist\nbuild\n.dist"


def test_app_settings_can_store_hidden_indexed_targets(tmp_path: Path, monkeypatch) -> None:
    """
    インデックス済みフォルダ一覧で隠したいキーワードは専用テキストファイルへ正規化して保持される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    hidden_keywords_path = tmp_path / "hidden_indexed_targets.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "hidden_indexed_targets_name", "hidden_indexed_targets.txt")

    saved_settings = service.update_app_settings(hidden_indexed_targets="obsidian\n\n Agent_Skills \nobsidian")

    assert saved_settings.hidden_indexed_targets == "obsidian\nAgent_Skills"
    assert hidden_keywords_path.read_text(encoding="utf-8") == "obsidian\nAgent_Skills"


def test_app_settings_can_store_synonym_groups(tmp_path: Path, monkeypatch) -> None:
    """
    アプリ設定として保存した同義語リストは、CSV 風 1 行 1 グループのテキストへ正規化して保持される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    synonym_groups_path = tmp_path / "synonym_groups.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "synonym_groups_name", "synonym_groups.txt")

    saved_settings = service.update_app_settings(
        synonym_groups="スマートフォン, スマホ, モバイル\nノートPC， ラップトップ, ノートpc\n単語"
    )

    assert saved_settings.synonym_groups == "スマートフォン,スマホ,モバイル\nノートPC,ラップトップ\n単語"
    assert synonym_groups_path.read_text(encoding="utf-8") == "スマートフォン,スマホ,モバイル\nノートPC,ラップトップ\n単語"


def test_app_settings_can_store_extension_files(tmp_path: Path, monkeypatch) -> None:
    """
    アプリ設定として保存した拡張子一覧は、役割ごとのテキストファイルへ正規化して保持される。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "index_selected_extensions_name", "index_selected_extensions.txt")
    monkeypatch.setattr(settings, "custom_content_extensions_name", "custom_content_extensions.txt")
    monkeypatch.setattr(settings, "custom_filename_extensions_name", "custom_filename_extensions.txt")

    saved_settings = service.update_app_settings(
        index_selected_extensions=".md\n.py\n.cae\n.py",
        custom_content_extensions="py\n dat \n.py",
        custom_filename_extensions=".cae\nCAE",
    )

    assert saved_settings.index_selected_extensions == ".cae\n.md\n.py"
    assert saved_settings.custom_content_extensions == ".py\n.dat"
    assert saved_settings.custom_filename_extensions == ".cae"
    assert (tmp_path / "index_selected_extensions.txt").read_text(encoding="utf-8") == ".cae\n.md\n.py"
    assert (tmp_path / "custom_content_extensions.txt").read_text(encoding="utf-8") == ".py\n.dat"
    assert (tmp_path / "custom_filename_extensions.txt").read_text(encoding="utf-8") == ".cae"


def test_app_settings_preserve_distinct_path_keyword_letter_case_variants(tmp_path: Path, monkeypatch) -> None:
    """
    パス形式の除外キーワードは大文字小文字違いを別物として保持する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    exclude_keywords_path = tmp_path / "exclude_keywords.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "exclude_keywords_name", "exclude_keywords.txt")

    saved_settings = service.update_app_settings(
        exclude_keywords="Agent_Skills/.\nagent_skills/.\n Build \nbuild"
    )

    assert saved_settings.exclude_keywords == "Agent_Skills/.\nagent_skills/.\nBuild"
    assert exclude_keywords_path.read_text(encoding="utf-8") == "Agent_Skills/.\nagent_skills/.\nBuild"


def test_reset_database_keeps_app_settings(tmp_path: Path, monkeypatch) -> None:
    """
    データベース初期化後もアプリ設定の除外キーワードは保持する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    exclude_keywords_path = tmp_path / "exclude_keywords.txt"
    hidden_keywords_path = tmp_path / "hidden_indexed_targets.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "exclude_keywords_name", "exclude_keywords.txt")
    monkeypatch.setattr(settings, "hidden_indexed_targets_name", "hidden_indexed_targets.txt")
    monkeypatch.setattr(settings, "synonym_groups_name", "synonym_groups.txt")
    monkeypatch.setattr(settings, "index_selected_extensions_name", "index_selected_extensions.txt")
    monkeypatch.setattr(settings, "custom_content_extensions_name", "custom_content_extensions.txt")
    monkeypatch.setattr(settings, "custom_filename_extensions_name", "custom_filename_extensions.txt")

    service.update_app_settings(
        exclude_keywords=".cache\ndist",
        hidden_indexed_targets="obsidian\nAgent_Skills",
        synonym_groups="スマートフォン,スマホ,モバイル",
        index_selected_extensions=".md\n.py",
        custom_content_extensions=".py",
        custom_filename_extensions=".cae",
    )
    service.reset_database()

    loaded_settings = service.get_app_settings()
    assert loaded_settings.exclude_keywords == ".cache\ndist"
    assert loaded_settings.hidden_indexed_targets == "obsidian\nAgent_Skills"
    assert loaded_settings.synonym_groups == "スマートフォン,スマホ,モバイル"
    assert loaded_settings.index_selected_extensions == ".md\n.py"
    assert loaded_settings.custom_content_extensions == ".py"
    assert loaded_settings.custom_filename_extensions == ".cae"
    assert exclude_keywords_path.read_text(encoding="utf-8") == ".cache\ndist"
    assert hidden_keywords_path.read_text(encoding="utf-8") == "obsidian\nAgent_Skills"


def test_app_settings_migrates_legacy_sqlite_value_to_text_file(tmp_path: Path, monkeypatch) -> None:
    """
    旧 SQLite 保存値がありテキストファイル未作成なら、初回読込時にファイルへ移行する。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)
    exclude_keywords_path = tmp_path / "exclude_keywords.txt"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "exclude_keywords_name", "exclude_keywords.txt")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            exclude_keywords TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        INSERT INTO app_settings (id, exclude_keywords, created_at, updated_at)
        VALUES (1, '.cache\nlegacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    connection.commit()

    loaded = service.get_app_settings()

    assert loaded.exclude_keywords == ".cache\nlegacy"
    assert exclude_keywords_path.read_text(encoding="utf-8") == ".cache\nlegacy"


def test_root_path_range_query_handles_filesystem_root(tmp_path: Path) -> None:
    """
    範囲クエリ最適化後も、ルートディレクトリ配下の既存レコードを正しく取得・削除できる。
    """
    connection = _create_connection(tmp_path)
    service = IndexService(connection=connection)

    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path, file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/tmp/example.md", "/tmp/example.md", "example.md", ".md", 0.0, 0.0, 10, "2026-04-13T00:00:00+00:00"),
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
