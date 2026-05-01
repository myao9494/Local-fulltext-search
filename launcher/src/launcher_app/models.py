"""
ランチャー UI と API クライアントで共有する検索結果モデルを定義する。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResultItem:
    """
    既存検索 API の結果 1 件をランチャーで扱いやすい形に変換した値。
    """

    file_id: int
    result_kind: str
    target_path: str
    file_name: str
    full_path: str
    file_ext: str
    created_at: str
    mtime: str
    click_count: int
    snippet: str


@dataclass(frozen=True)
class SearchResponse:
    """
    ランチャー検索で必要な件数と結果一覧を保持する。
    """

    total: int
    items: list[SearchResultItem]
    has_more: bool = False
