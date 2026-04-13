r"""
Windows の UNC パス正規化を検証する。
`\\server\share\folder` 形式を検索用の正規化文字列へ安全に変換できることを担保する。
"""

from pathlib import PureWindowsPath

from app.services.path_service import get_descendant_path_prefix, get_descendant_path_range, normalize_path_str


def test_normalize_path_str_preserves_windows_unc_path() -> None:
    """
    Windows の UNC パスは共有名を壊さずに POSIX 風の区切りへ正規化する。
    """
    raw_path = r"\\hikoka\sss\日報"

    assert normalize_path_str(raw_path) == PureWindowsPath(raw_path).as_posix()


def test_descendant_path_helpers_handle_root_paths() -> None:
    """
    ルートディレクトリでも子孫パス用の接頭辞・範囲境界を壊さず生成する。
    """
    assert get_descendant_path_prefix("/") == "/"
    assert get_descendant_path_prefix("C:/") == "C:/"

    unix_start, unix_end = get_descendant_path_range("/")
    windows_start, windows_end = get_descendant_path_range("C:/")

    assert unix_start == "/"
    assert unix_end.startswith("/")
    assert windows_start == "C:/"
    assert windows_end.startswith("C:/")
