"""
検索リクエストモデルの入力制約を検証する。
検索対象パスと作成日フィルタが安全な形で受理されることを担保する。
"""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.search import SearchQueryParams


def test_search_query_params_accepts_absolute_full_path(tmp_path: Path) -> None:
    """
    検索対象 full_path は絶対パスなら受け付ける。
    """
    target = tmp_path / "docs"
    target.mkdir()

    params = SearchQueryParams(
        q="alpha",
        full_path=str(target),
        index_depth=5,
    )

    assert params.full_path == str(target)


def test_search_query_params_rejects_relative_full_path() -> None:
    """
    検索対象 full_path に相対パスを渡すとバリデーションエラーにする。
    """
    with pytest.raises(ValidationError):
        SearchQueryParams(
            q="alpha",
            full_path="docs",
            index_depth=5,
        )


def test_search_query_params_accepts_windows_unc_full_path() -> None:
    """
    Windows の UNC パスは絶対パス相当として受け付ける。
    """
    params = SearchQueryParams(
        q="alpha",
        full_path=r"\\hikoka\sss\日報",
        index_depth=5,
    )

    assert params.full_path == r"\\hikoka\sss\日報"


def test_search_query_params_accepts_empty_full_path_for_global_search() -> None:
    """
    全データベース検索モードでは full_path の空文字を受け付ける。
    """
    params = SearchQueryParams(
        q="alpha",
        full_path="",
        index_depth=5,
    )

    assert params.full_path == ""


def test_search_query_params_accepts_created_date_range() -> None:
    """
    作成日の開始日と終了日は日付型として受け付ける。
    """
    params = SearchQueryParams(
        q="alpha",
        full_path="",
        index_depth=5,
        date_field="created",
        created_from=date(2026, 4, 1),
        created_to=date(2026, 4, 30),
    )

    assert params.created_from == date(2026, 4, 1)
    assert params.created_to == date(2026, 4, 30)


def test_search_query_params_rejects_reversed_created_date_range() -> None:
    """
    作成日終了が開始日より前の逆転範囲は受け付けない。
    """
    with pytest.raises(ValidationError):
        SearchQueryParams(
            q="alpha",
            full_path="",
            index_depth=5,
            date_field="modified",
            created_from=date(2026, 4, 30),
            created_to=date(2026, 4, 1),
        )


def test_search_query_params_accepts_modified_date_field() -> None:
    """
    日付フィルタ種別は編集日指定も受け付ける。
    """
    params = SearchQueryParams(
        q="alpha",
        full_path="",
        index_depth=5,
        date_field="modified",
    )

    assert params.date_field == "modified"
