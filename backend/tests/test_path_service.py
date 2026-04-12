r"""
Windows の UNC パス正規化を検証する。
`\\server\share\folder` 形式を検索用の正規化文字列へ安全に変換できることを担保する。
"""

from pathlib import PureWindowsPath

from app.services.path_service import normalize_path_str


def test_normalize_path_str_preserves_windows_unc_path() -> None:
    """
    Windows の UNC パスは共有名を壊さずに POSIX 風の区切りへ正規化する。
    """
    raw_path = r"\\hikoka\sss\日報"

    assert normalize_path_str(raw_path) == PureWindowsPath(raw_path).as_posix()
