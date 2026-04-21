import os
import platform
import subprocess
from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db_connection
from app.models.files import OpenFileLocationRequest

router = APIRouter(prefix="/api/files", tags=["files"])


@router.delete("/{file_id}")
def delete_file(
    file_id: int, connection: Connection = Depends(get_db_connection)
) -> dict[str, object]:
    """
    指定された file_id のファイルをOS上から物理削除し、
    インデックス（DB）からも除外する。
    """
    cursor = connection.execute("SELECT full_path FROM files WHERE id = ?", (file_id,))
    row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found in index."
        )

    full_path = str(row[0])

    try:
        os.remove(full_path)
    except FileNotFoundError:
        # 既に存在しない場合はスキップしてDBからの削除のみ行う
        pass
    except Exception as e:
        # 権限エラー等で削除できない場合は500を返す
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete physical file: {e}",
        ) from e

    _delete_file_from_db(file_id, connection)

    return {"status": "success", "file_id": file_id}


def _delete_file_from_db(file_id: int, connection: Connection) -> None:
    # FTS5 のトリガーが設定されていれば、file_segments の DELETE 時に FTS のインデックスも削除される
    connection.execute("DELETE FROM file_segments WHERE file_id = ?", (file_id,))
    connection.execute("DELETE FROM files WHERE id = ?", (file_id,))
    connection.commit()


@router.post("/open-location")
def open_file_location(payload: OpenFileLocationRequest) -> dict[str, str]:
    """
    指定パスの位置を macOS では Finder、Windows では Explorer で開く。
    """
    system_name = platform.system()
    if system_name == "Darwin":
        _open_folder_macos(payload.path)
        return {"status": "success"}
    if system_name == "Windows":
        _open_folder_windows(payload.path)
        return {"status": "success"}
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Open location is supported only on macOS and Windows.",
    )


def _open_folder_macos(path: str) -> None:
    """
    Finder で対象ファイルまたはフォルダの位置を表示する。
    """
    result = subprocess.run(
        ["/usr/bin/open", "-R", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Finder failed to open the file location.",
        )


def _open_folder_windows(path: str) -> None:
    """
    Explorer で対象ファイルまたはフォルダの位置を表示する。
    """
    result = subprocess.run(
        ["explorer.exe", "/select,", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Explorer failed to open the file location.",
        )
