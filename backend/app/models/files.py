"""
ファイル削除やファイル位置オープン API の入力モデルを定義する。
絶対パスまたは Windows UNC パスだけを受け付ける。
"""

from pydantic import BaseModel, field_validator

from app.models.search import _validate_absolute_path_or_unc


class OpenFileLocationRequest(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path_is_absolute(cls, value: str) -> str:
        """
        Finder / Explorer に渡すパスは絶対パスまたは UNC パスだけを受け付ける。
        """
        return _validate_absolute_path_or_unc(value, field_name="path")
