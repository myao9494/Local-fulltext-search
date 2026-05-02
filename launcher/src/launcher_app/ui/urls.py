"""
ランチャー UI から Web アプリ互換 URL を生成する。
"""

import os
from urllib.parse import quote

from launcher_app.models import SearchResultItem


def folder_path_for_item(item: SearchResultItem) -> str:
    """
    Web アプリの getFolderPath と同じ用途で、ファイルの親フォルダを返す。
    """
    if item.result_kind == "folder":
        return item.full_path
    folder_path = os.path.dirname(item.full_path)
    return folder_path or item.full_path


def full_path_web_url(path: str, base_url: str = "http://localhost:8001") -> str:
    """
    Web アプリの fullPathUrl と同じ URL を生成する。
    """
    return f"{base_url}/api/fullpath?path={quote(path, safe='')}"


def folder_web_url(path: str, base_url: str = "http://localhost:8001") -> str:
    """
    Web アプリの folderUrl と同じ URL を生成する。
    """
    return f"{base_url}/?path={quote(path, safe='')}"


def primary_web_url_for_item(item: SearchResultItem, base_url: str = "http://localhost:8001") -> str:
    """
    Web アプリの primaryUrl と同じ URL を生成する。
    """
    if item.result_kind == "folder":
        return folder_web_url(item.full_path, base_url)
    return full_path_web_url(item.full_path, base_url)


def folder_web_url_for_item(item: SearchResultItem, base_url: str = "http://localhost:8001") -> str:
    """
    Web アプリのフォルダリンクと同じ URL を生成する。
    """
    return folder_web_url(folder_path_for_item(item), base_url)
