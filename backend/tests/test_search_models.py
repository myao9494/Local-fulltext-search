"""
検索リクエストモデルの入力制約を検証する。
検索対象の full_path が絶対パス前提で扱われることを担保する。
"""

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
