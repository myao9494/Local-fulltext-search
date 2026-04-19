"""
ファイル削除 API の振る舞いを検証する。
"""

from unittest.mock import MagicMock, call

import pytest
from fastapi import HTTPException

from app.api.files import _delete_file_from_db, delete_file


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
