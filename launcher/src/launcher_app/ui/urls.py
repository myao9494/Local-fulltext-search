"""
ランチャー UI から Web アプリ互換 URL を生成する。
"""

import os
import platform
import subprocess
from urllib.parse import quote

from launcher_app.models import SearchResultItem

SYSTEM_LAUNCH_EXTENSIONS = frozenset({".py", ".bat", ".exe", ".lnk"})


def uses_system_file_launcher(path: str) -> bool:
    """スクリプト・実行ファイル・ショートカットはOpenハブを経由せずOSで起動する。"""
    return os.path.splitext(path)[1].lower() in SYSTEM_LAUNCH_EXTENSIONS


def open_with_system_file_launcher(path: str) -> None:
    """指定スクリプトを親フォルダをcurrent dirとしてOS既定の関連付けで起動する。"""
    working_directory = os.path.dirname(path) or os.getcwd()
    if platform.system() == "Windows":
        # start の /d は関連付け先（Python等）の current dir を明示できる。
        subprocess.Popen(["cmd", "/c", "start", "", "/d", working_directory, path])
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path], cwd=working_directory)
    else:
        subprocess.Popen(["xdg-open", path], cwd=working_directory)


def folder_path_for_item(item: SearchResultItem) -> str:
    """
    Web アプリの getFolderPath と同じ用途で、ファイルの親フォルダを返す。
    """
    if item.result_kind == "folder":
        return item.full_path
    folder_path = os.path.dirname(item.full_path)
    return folder_path or item.full_path


def full_path_web_url(path: str, base_url: str = "http://127.0.0.1:8001") -> str:
    """
    Web アプリの fullPathUrl と同じ URL を生成する。
    """
    return f"{base_url.rstrip('/')}/api/fullpath?path={quote(path, safe='')}"


def folder_web_url(path: str, base_url: str = "http://127.0.0.1:8001") -> str:
    """
    Web アプリの folderUrl と同じ URL を生成する。
    """
    return f"{base_url.rstrip('/')}/?path={quote(path, safe='')}"


def primary_web_url_for_item(item: SearchResultItem, base_url: str = "http://127.0.0.1:8001") -> str:
    """
    Web アプリの primaryUrl と同じ URL を生成する。
    """
    if item.result_kind == "folder":
        return folder_web_url(item.full_path, base_url)
    return full_path_web_url(item.full_path, base_url)


def folder_web_url_for_item(item: SearchResultItem, base_url: str = "http://127.0.0.1:8001") -> str:
    """
    Web アプリのフォルダリンクと同じ URL を生成する。
    """
    return folder_web_url(folder_path_for_item(item), base_url)
