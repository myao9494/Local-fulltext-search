"""
検索結果を OS 標準アプリまたはファイルマネージャーで開く処理を提供する。
"""

import os
import platform
from pathlib import PureWindowsPath
import subprocess


class FileActionError(RuntimeError):
    """
    ファイル起動または位置表示に失敗したことを表す。
    """


def open_path(path: str) -> None:
    """
    対象ファイルまたはフォルダを OS 標準のアプリケーションで開く。
    """
    system_name = platform.system()
    if system_name == "Darwin":
        _run_command(["/usr/bin/open", path])
        return
    if system_name == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    _run_command(["xdg-open", path])


def reveal_path(path: str) -> None:
    """
    対象ファイルの保存場所を OS のファイルマネージャーで表示する。
    """
    system_name = platform.system()
    if system_name == "Darwin":
        _run_command(["/usr/bin/open", "-R", path])
        return
    if system_name == "Windows":
        normalized_path = str(PureWindowsPath(path))
        command = ["explorer.exe", normalized_path] if os.path.isdir(path) else ["explorer.exe", "/select,", normalized_path]
        _run_command(command)
        return
    folder_path = path if os.path.isdir(path) else os.path.dirname(path)
    _run_command(["xdg-open", folder_path or "."])


def _run_command(command: list[str]) -> None:
    """
    OS コマンドを実行し、失敗時は標準エラーを含む例外へ変換する。
    """
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "OS command failed."
        raise FileActionError(message)
