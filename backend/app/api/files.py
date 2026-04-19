import os
from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db_connection

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
