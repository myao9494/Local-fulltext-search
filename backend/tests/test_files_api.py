"""
ファイル削除 API とファイル位置オープン API の振る舞いを検証する。
"""

import platform
import subprocess
from unittest.mock import MagicMock, call

import pytest
from fastapi import HTTPException

from app.api.files import (
    _delete_file_from_db,
    _open_folder_macos,
    _open_folder_windows,
    delete_file,
    open_file_location,
)
from app.models.files import OpenFileLocationRequest


def test_delete_file_removes_from_db_and_os(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    DELETE /api/files/{file_id} は DB からパスを取得し、物理削除した上で DB からも削除する。
    """
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    
    # Return mock path for the file_id
    mock_cursor.fetchone.return_value = ("/mock/path/test.txt",)
    mock_connection.execute.return_value = mock_cursor
    
    mock_os_remove = MagicMock()
    monkeypatch.setattr("os.remove", mock_os_remove)
    
    result = delete_file(file_id=123, connection=mock_connection)
    
    assert result == {"status": "success", "file_id": 123}
    
    # 物理削除が呼ばれたか
    mock_os_remove.assert_called_once_with("/mock/path/test.txt")
    
    # DB削除が呼ばれたか
    expected_calls = [
        call("SELECT full_path FROM files WHERE id = ?", (123,)),
        call("DELETE FROM file_segments WHERE file_id = ?", (123,)),
        call("DELETE FROM files WHERE id = ?", (123,)),
    ]
    mock_connection.execute.assert_has_calls(expected_calls, any_order=True)
    mock_connection.commit.assert_called_once()


def test_delete_file_skips_os_remove_if_file_not_found_but_deletes_from_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    ファイルが存在しない(FileNotFoundError)場合でも DB からの削除は続行する。
    """
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("/mock/path/missing.txt",)
    mock_connection.execute.return_value = mock_cursor
    
    def fake_remove(path: str) -> None:
        raise FileNotFoundError(f"No such file: {path}")
        
    monkeypatch.setattr("os.remove", fake_remove)
    
    result = delete_file(file_id=123, connection=mock_connection)
    
    assert result == {"status": "success", "file_id": 123}
    mock_connection.execute.assert_any_call("DELETE FROM files WHERE id = ?", (123,))
    mock_connection.commit.assert_called_once()


def test_delete_file_raises_404_if_file_id_not_in_db() -> None:
    """
    DB に指定された file_id がない場合は 404 エラーをスローする。
    """
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_connection.execute.return_value = mock_cursor
    
    with pytest.raises(HTTPException) as exc_info:
        delete_file(file_id=999, connection=mock_connection)
        
    assert exc_info.value.status_code == 404
    assert "File not found in index" in exc_info.value.detail


def test_open_file_location_uses_finder_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    macOS では open -R で Finder 上のファイル位置を表示する。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = open_file_location(OpenFileLocationRequest(path="/tmp/docs/file.txt"))

    assert result == {"status": "success"}
    assert captured["command"] == ["/usr/bin/open", "-R", "/tmp/docs/file.txt"]


def test_open_file_location_uses_explorer_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Windows では explorer.exe /select, で対象ファイル位置を表示する。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("os.path.isdir", lambda path: False)

    result = open_file_location(OpenFileLocationRequest(path="C:/docs/file.txt"))

    assert result == {"status": "success"}
    assert captured["command"] == ["explorer.exe", "/select,", "C:\\docs\\file.txt"]


def test_open_file_location_opens_folder_directly_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Windows ではフォルダを選択表示ではなく、そのフォルダ自体を開く。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("os.path.isdir", lambda path: True)

    result = open_file_location(OpenFileLocationRequest(path="C:/docs"))

    assert result == {"status": "success"}
    assert captured["command"] == ["explorer.exe", "C:\\docs"]


def test_open_file_location_rejects_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    非対応 OS では 501 を返す。
    """
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    with pytest.raises(HTTPException) as error_info:
        open_file_location(OpenFileLocationRequest(path="/tmp/docs/file.txt"))

    assert error_info.value.status_code == 501


def test_open_file_location_requires_absolute_path() -> None:
    """
    位置オープン API は相対パスを受け付けない。
    """
    with pytest.raises(ValueError):
        OpenFileLocationRequest(path="docs/file.txt")


def test_open_folder_macos_raises_when_finder_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Finder 起動に失敗した場合は 500 エラーへ変換する。
    """
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HTTPException) as error_info:
        _open_folder_macos("/tmp/docs/file.txt")

    assert error_info.value.status_code == 500


def test_open_folder_windows_raises_when_explorer_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Explorer 起動に失敗した場合は 500 エラーへ変換する。
    """
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HTTPException) as error_info:
        _open_folder_windows("C:/docs/file.txt")

    assert error_info.value.status_code == 500
