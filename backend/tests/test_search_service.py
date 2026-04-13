"""
検索サービスの FTS5 クエリ組み立てと検索挙動を検証する。
特殊文字を含む検索語でも internal error にせず、本文検索できることを担保する。
"""

from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from app.db.schema import initialize_schema
from app.models.search import SearchQueryParams
from app.services.search_service import SearchService


def test_search_handles_special_characters_without_fts_errors(tmp_path: Path) -> None:
    """
    FTS5 の記号を含む検索語でも検索できる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "symbols.md").write_text("hello-world foo/bar c++ [test]", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="hello-world",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["symbols.md"]


def test_search_matches_japanese_substring_inside_longer_token(tmp_path: Path) -> None:
    """
    日本語の連続文字列は bi-gram 補助インデックスで部分一致検索できる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "sushi.md").write_text("今日はお寿司が食べたい。", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="寿司",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["sushi.md"]
    assert "<mark>寿司</mark>" in result.items[0].snippet


def test_search_matches_mixed_ascii_and_japanese_terms(tmp_path: Path) -> None:
    """
    ASCII 語と日本語語を混在させた AND 検索でも、同じ本文からヒットできる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "mixed.md").write_text("lunch memo: 今日はお寿司が食べたい。", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="lunch 寿司",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["mixed.md"]
    assert "<mark>lunch</mark>" in result.items[0].snippet
    assert "<mark>寿司</mark>" in result.items[0].snippet


def test_search_requires_all_whitespace_separated_terms(tmp_path: Path) -> None:
    """
    空白区切りの複数語は AND 条件として検索する。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "match.md").write_text("alpha beta gamma", encoding="utf-8")
    (target / "partial.md").write_text("alpha only", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="alpha beta",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["match.md"]


def test_search_preserves_total_when_offset_page_is_empty(tmp_path: Path) -> None:
    """
    OFFSET で結果ページが空になっても、総件数は失われない。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "match.md").write_text("alpha beta gamma", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
            limit=10,
            offset=10,
        )
    )

    assert result.total == 1
    assert result.items == []


def test_search_supports_large_limit_values(tmp_path: Path) -> None:
    """
    file_manager 連携のため、100件を超える limit でも検索結果を返せる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()

    for index in range(150):
        (target / f"memo_{index:03d}.md").write_text("alpha memo", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
            limit=150,
        )
    )

    assert result.total == 150
    assert len(result.items) == 150


def test_search_supports_regex_mode_for_content_matches(tmp_path: Path) -> None:
    """
    正規表現モードでは Python 互換の正規表現で本文検索できる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "release.md").write_text("version 1.2.3", encoding="utf-8")
    (target / "plain.md").write_text("version 1x2x3", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q=r"1\.\d\.\d",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
            regex_enabled=True,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["release.md"]


def test_search_rejects_invalid_regex_pattern(tmp_path: Path) -> None:
    """
    不正な正規表現は利用者向けのエラーとして扱う。
    """
    from fastapi import HTTPException

    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "sample.md").write_text("alpha beta gamma", encoding="utf-8")

    try:
        service.search(
            SearchQueryParams(
                q="(",
                full_path=str(target),
                index_depth=5,
                refresh_window_minutes=60,
                regex_enabled=True,
            )
        )
    except HTTPException as error:
        assert error.status_code == 400
        assert "正規表現" in str(error.detail)
    else:
        raise AssertionError("HTTPException was not raised for invalid regex pattern")


def test_search_matches_windows_unc_target_path(tmp_path: Path) -> None:
    """
    Windows の UNC パスを検索対象にしても、正規化済みパスと一致して検索できる。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            "//hikoka/sss/日報/2026-04-13.md",
            "//hikoka/sss/日報/2026-04-13.md",
            "2026-04-13.md",
            ".md",
            datetime(2026, 4, 13, tzinfo=UTC).timestamp(),
            12,
            indexed_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (1, 'body', ?, ?)
        """,
        ("//hikoka/sss/日報/2026-04-13.md", "daily report memo"),
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="report",
            full_path=r"\\hikoka\sss\日報",
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.full_path for item in result.items] == ["//hikoka/sss/日報/2026-04-13.md"]


def test_search_matches_filename_only_image_in_normal_mode(tmp_path: Path) -> None:
    """
    本文を持たない画像ファイルでも、ファイル名一致なら通常検索でヒットする。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "architecture-overview.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = service.search(
        SearchQueryParams(
            q="overview",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types=".png",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["architecture-overview.png"]


def test_search_matches_filename_only_image_in_regex_mode(tmp_path: Path) -> None:
    """
    本文を持たない画像ファイルでも、正規表現モードでファイル名検索できる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "architecture-overview.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = service.search(
        SearchQueryParams(
            q=r"architecture.*overview",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            regex_enabled=True,
            types=".png",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["architecture-overview.png"]


def test_search_root_target_respects_depth_filter(tmp_path: Path) -> None:
    """
    ルートディレクトリ対象でも index_depth に応じて検索範囲を正しく絞り込む。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    timestamp = datetime(2026, 4, 13, tzinfo=UTC).timestamp()
    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/match-root.md", "/match-root.md", "match-root.md", ".md", timestamp, 12, indexed_at),
    )
    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/tmp/match-nested.md", "/tmp/match-nested.md", "match-nested.md", ".md", timestamp, 12, indexed_at),
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="match",
            full_path="/",
            index_depth=0,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.full_path for item in result.items] == ["/match-root.md"]


def _create_connection(tmp_path: Path) -> Connection:
    """
    テストごとの一時 SQLite 接続を作成する。
    """
    import sqlite3

    connection = sqlite3.connect(tmp_path / "search.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    initialize_schema(connection)
    return connection
