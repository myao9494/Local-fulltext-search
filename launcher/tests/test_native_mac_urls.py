"""
macOS ランチャーが Web アプリと同じ検索結果 URL を生成することを検証する。
"""

from launcher_app.models import SearchResultItem
from launcher_app.ui.urls import (
    folder_path_for_item,
    folder_web_url_for_item,
    full_path_web_url,
    primary_web_url_for_item,
)


def make_item(*, result_kind: str, full_path: str) -> SearchResultItem:
    """
    URL 生成テスト用の最小検索結果を作る。
    """
    return SearchResultItem(
        file_id=1,
        result_kind=result_kind,
        target_path=full_path,
        file_name=full_path.rsplit("/", maxsplit=1)[-1],
        full_path=full_path,
        file_ext=".md",
        created_at="2026-01-01T00:00:00",
        mtime="2026-01-01T00:00:00",
        click_count=0,
        snippet="",
    )


def test_file_primary_url_matches_web_app_fullpath_url() -> None:
    """
    ファイル結果は Web アプリ同様 /api/fullpath?path=... を開く。
    """
    item = make_item(result_kind="file", full_path="/tmp/docs/a b.md")

    assert primary_web_url_for_item(item) == "http://127.0.0.1:8079/api/fullpath?path=%2Ftmp%2Fdocs%2Fa%20b.md"


def test_folder_primary_url_matches_web_app_folder_url() -> None:
    """
    フォルダ結果は Web アプリ同様 /?path=... を開く。
    """
    item = make_item(result_kind="folder", full_path="/tmp/docs")

    assert primary_web_url_for_item(item) == "http://127.0.0.1:8079/?path=%2Ftmp%2Fdocs"


def test_folder_link_uses_parent_for_file_results() -> None:
    """
    ファイル結果のフォルダリンクは親フォルダ URL を開く。
    """
    item = make_item(result_kind="file", full_path="/tmp/docs/a.md")

    assert folder_path_for_item(item) == "/tmp/docs"
    assert folder_web_url_for_item(item) == "http://127.0.0.1:8079/?path=%2Ftmp%2Fdocs"


def test_full_path_url_encodes_japanese_paths() -> None:
    """
    日本語パスも Web アプリの encodeURIComponent 相当でエンコードする。
    """
    assert full_path_web_url("/tmp/明和高校.md") == (
        "http://127.0.0.1:8079/api/fullpath?path=%2Ftmp%2F%E6%98%8E%E5%92%8C%E9%AB%98%E6%A0%A1.md"
    )
