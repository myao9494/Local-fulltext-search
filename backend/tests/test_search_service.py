"""
検索サービスの FTS5 クエリ組み立てと検索挙動を検証する。
特殊文字を含む検索語でも internal error にせず、本文検索できることを担保する。
"""

from datetime import UTC, date, datetime
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


def test_search_allows_terms_to_be_satisfied_across_filename_and_body(tmp_path: Path) -> None:
    """
    空白区切りの複数語は、ファイル名と本文に分散していても同一ファイルならヒットする。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "クラリネット.md").write_text("木管楽器のメモです。", encoding="utf-8")
    (target / "楽器まとめ.md").write_text("弦楽器のメモです。", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="クラリネット 楽器",
            full_path=str(target),
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["クラリネット.md"]
    assert "<mark>クラリネット</mark>" in result.items[0].snippet or "<mark>楽器</mark>" in result.items[0].snippet


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
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            "//hikoka/sss/日報/2026-04-13.md",
            "//hikoka/sss/日報/2026-04-13.md",
            "2026-04-13.md",
            ".md",
            datetime(2026, 4, 13, tzinfo=UTC).timestamp(),
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


def test_search_filters_results_by_created_date_range(tmp_path: Path) -> None:
    """
    作成日フィルタを指定すると、その日付範囲に入るファイルだけを返す。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    rows = [
        (
            "/docs/old.md",
            "/docs/old.md",
            "old.md",
            ".md",
            datetime(2026, 4, 10, 9, 0).astimezone().timestamp(),
            datetime(2026, 4, 13, tzinfo=UTC).timestamp(),
            12,
            indexed_at,
        ),
        (
            "/docs/new.md",
            "/docs/new.md",
            "new.md",
            ".md",
            datetime(2026, 4, 15, 12, 0).astimezone().timestamp(),
            datetime(2026, 4, 13, tzinfo=UTC).timestamp(),
            12,
            indexed_at,
        ),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/docs/old.md", "alpha old memo"),
            (2, "/docs/new.md", "alpha new memo"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
            created_from=date(2026, 4, 12),
            created_to=date(2026, 4, 16),
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["new.md"]


def test_search_filters_results_by_modified_date_range(tmp_path: Path) -> None:
    """
    編集日モードでは mtime を使って日付範囲を絞り込む。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    rows = [
        (
            "/docs/old.md",
            "/docs/old.md",
            "old.md",
            ".md",
            datetime(2026, 4, 1, 9, 0).astimezone().timestamp(),
            datetime(2026, 4, 10, 9, 0).astimezone().timestamp(),
            12,
            indexed_at,
        ),
        (
            "/docs/new.md",
            "/docs/new.md",
            "new.md",
            ".md",
            datetime(2026, 4, 1, 9, 0).astimezone().timestamp(),
            datetime(2026, 4, 15, 12, 0).astimezone().timestamp(),
            12,
            indexed_at,
        ),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/docs/old.md", "alpha old memo"),
            (2, "/docs/new.md", "alpha new memo"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
            date_field="modified",
            created_from=date(2026, 4, 12),
            created_to=date(2026, 4, 16),
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["new.md"]
    assert result.items[0].created_at == datetime.fromtimestamp(rows[1][4], tz=UTC)


def test_search_uses_independent_index_types_for_refresh_target(tmp_path: Path) -> None:
    """
    再インデックス判定に渡す拡張子は検索フィルタと分離し、index_types だけを使う。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "memo.md").write_text("alpha memo", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_ensure_fresh_target(**kwargs) -> None:
        captured.update(kwargs)

    service.index_service.ensure_fresh_target = fake_ensure_fresh_target

    service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            index_types="md",
            types="png",
        )
    )

    assert captured["types"] == "md"


def test_search_extension_filter_accepts_space_separated_values_without_dots(tmp_path: Path) -> None:
    """
    検索時の拡張子フィルタは、スペース区切り・ドットなし入力でも正しく絞り込める。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "board.excalidraw").write_text('{"text":"alpha board"}', encoding="utf-8")
    (target / "memo.md").write_text("alpha memo", encoding="utf-8")

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types="excalidraw",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["board.excalidraw"]


def test_search_treats_md_and_excalidraw_md_as_distinct_extensions(tmp_path: Path) -> None:
    """
    `.md` と `.excalidraw.md` は別拡張子として検索フィルタできる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "memo.md").write_text("alpha memo", encoding="utf-8")
    (target / "board.excalidraw.md").write_text("alpha board", encoding="utf-8")

    markdown_result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types="md",
        )
    )
    excalidraw_result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types="excalidraw.md",
        )
    )

    assert [item.file_name for item in markdown_result.items] == ["memo.md"]
    assert [item.file_name for item in excalidraw_result.items] == ["board.excalidraw.md"]


def test_search_treats_svg_and_dio_svg_as_distinct_extensions(tmp_path: Path) -> None:
    """
    `.svg` と `.dio.svg` は別拡張子として検索フィルタできる。
    """
    service = SearchService(connection=_create_connection(tmp_path))
    target = tmp_path / "docs"
    target.mkdir()
    (target / "icon.svg").write_bytes(b"<svg/>")
    (target / "flow.dio.svg").write_text("<svg><text>alpha flow</text></svg>", encoding="utf-8")

    svg_result = service.search(
        SearchQueryParams(
            q="flow",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types="svg",
        )
    )
    dio_svg_result = service.search(
        SearchQueryParams(
            q="flow",
            full_path=str(target),
            index_depth=0,
            refresh_window_minutes=60,
            types="dio.svg",
        )
    )

    assert svg_result.items == []
    assert [item.file_name for item in dio_svg_result.items] == ["flow.dio.svg"]


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
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/match-root.md", "/match-root.md", "match-root.md", ".md", timestamp, timestamp, 12, indexed_at),
    )
    connection.execute(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        ("/tmp/match-nested.md", "/tmp/match-nested.md", "match-nested.md", ".md", timestamp, timestamp, 12, indexed_at),
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


def test_search_does_not_exclude_results_by_ancestor_directory_name(tmp_path: Path) -> None:
    """
    検索時の除外判定は対象配下に限定し、絶対パス上の親ディレクトリ名では落とさない。
    """
    workspace_root = tmp_path / "app" / "project"
    docs_dir = workspace_root / "docs"
    docs_dir.mkdir(parents=True)
    note_path = docs_dir / "guide.md"
    note_path.write_text("全文検索のメモです。", encoding="utf-8")

    service = SearchService(connection=_create_connection(tmp_path))

    result = service.search(
        SearchQueryParams(
            q="全文",
            full_path=str(workspace_root),
            index_depth=5,
            refresh_window_minutes=60,
            exclude_keywords="app",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["guide.md"]


def test_search_without_full_path_matches_across_entire_database(tmp_path: Path) -> None:
    """
    full_path を空にすると、DB 全体を対象に検索できる。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    timestamp = datetime(2026, 4, 13, tzinfo=UTC).timestamp()
    rows = [
        ("/docs/alpha.md", "/docs/alpha.md", "alpha.md", ".md", timestamp, timestamp, 12, indexed_at),
        ("/archive/alpha-notes.md", "/archive/alpha-notes.md", "alpha-notes.md", ".md", timestamp, timestamp, 12, indexed_at),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/docs/alpha.md", "alpha project memo"),
            (2, "/archive/alpha-notes.md", "alpha archive memo"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
        )
    )

    assert result.total == 2
    assert [item.file_name for item in result.items] == ["alpha.md", "alpha-notes.md"]
    assert all(item.target_path == "" for item in result.items)


def test_search_without_full_path_applies_exclude_keywords_to_entire_database(tmp_path: Path) -> None:
    """
    全 DB 検索では除外キーワードを絶対パス全体へ適用する。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    timestamp = datetime(2026, 4, 13, tzinfo=UTC).timestamp()
    rows = [
        ("/docs/alpha.md", "/docs/alpha.md", "alpha.md", ".md", timestamp, timestamp, 12, indexed_at),
        ("/archive/alpha-notes.md", "/archive/alpha-notes.md", "alpha-notes.md", ".md", timestamp, timestamp, 12, indexed_at),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/docs/alpha.md", "alpha project memo"),
            (2, "/archive/alpha-notes.md", "alpha archive memo"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
            exclude_keywords="archive",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["alpha.md"]


def test_search_without_full_path_excludes_relative_nested_directory_path(tmp_path: Path) -> None:
    """
    全 DB 検索では相対ディレクトリパス形式の除外キーワードも絶対パス結果へ適用できる。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    timestamp = datetime(2026, 4, 13, tzinfo=UTC).timestamp()
    rows = [
        (
            "/workspace/Agent_Skills/.roo/secret.md",
            "/workspace/Agent_Skills/.roo/secret.md",
            "secret.md",
            ".md",
            timestamp,
            timestamp,
            12,
            indexed_at,
        ),
        (
            "/workspace/Agent_SkillsX/.roo/keep.md",
            "/workspace/Agent_SkillsX/.roo/keep.md",
            "keep.md",
            ".md",
            timestamp,
            timestamp,
            12,
            indexed_at,
        ),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/workspace/Agent_Skills/.roo/secret.md", "agent secret"),
            (2, "/workspace/Agent_SkillsX/.roo/keep.md", "agent keep"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="agent",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
            exclude_keywords="Agent_Skills/.roo",
        )
    )

    assert result.total == 1
    assert [item.file_name for item in result.items] == ["keep.md"]


def test_search_without_full_path_excludes_dot_prefixed_directory_keyword(tmp_path: Path) -> None:
    """
    全 DB 検索では `.gemini` のようなドット始まりディレクトリ名も除外できる。
    """
    connection = _create_connection(tmp_path)
    service = SearchService(connection=connection)
    service.index_service.ensure_fresh_target = lambda **_: None

    indexed_at = datetime(2026, 4, 13, tzinfo=UTC).isoformat()
    timestamp = datetime(2026, 4, 13, tzinfo=UTC).timestamp()
    rows = [
        ("/workspace/docs/alpha.md", "/workspace/docs/alpha.md", "alpha.md", ".md", timestamp, timestamp, 12, indexed_at),
        ("/workspace/.gemini/secret.md", "/workspace/.gemini/secret.md", "secret.md", ".md", timestamp, timestamp, 12, indexed_at),
    ]
    connection.executemany(
        """
        INSERT INTO files(
            full_path, normalized_path,
            file_name, file_ext, created_at, mtime, size, indexed_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO file_segments(file_id, segment_type, segment_label, content)
        VALUES (?, 'body', ?, ?)
        """,
        [
            (1, "/workspace/docs/alpha.md", "alpha project memo"),
            (2, "/workspace/.gemini/secret.md", "alpha secret memo"),
        ],
    )
    connection.commit()

    result = service.search(
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            refresh_window_minutes=60,
            exclude_keywords=".gemini",
        )
    )

    assert result.total == 1
    assert [item.full_path for item in result.items] == ["/workspace/docs/alpha.md"]


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
