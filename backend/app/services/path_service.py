r"""
Windows の UNC パスと通常パスの正規化を扱う。
`\\server\share\...` 形式は共有名を壊さずに保持し、検索用文字列では POSIX 風区切りへそろえる。
"""

from pathlib import Path, PureWindowsPath


def normalize_path(raw_path: str | Path) -> Path:
    """
    実ファイルアクセス向けの Path を返す。
    Windows の UNC パスは `resolve()` で壊さないよう、そのまま `Path` として扱う。
    """
    raw_value = str(raw_path)
    if _is_windows_unc_path(raw_value):
        return Path(raw_value).expanduser()
    return Path(raw_path).expanduser().resolve()


def normalize_path_str(raw_path: str | Path) -> str:
    """
    DB 保存や検索比較用に、Windows の UNC パスを `//server/share/...` 形式へ正規化する。
    """
    raw_value = str(raw_path)
    if _is_windows_unc_path(raw_value):
        return PureWindowsPath(raw_value).as_posix()
    return normalize_path(raw_path).as_posix()


def get_relative_path(root_path: Path, target_path: Path) -> Path:
    return target_path.relative_to(root_path)


def get_depth(relative_path: Path) -> int:
    return len(relative_path.parts) - 1


def _is_windows_unc_path(raw_path: str) -> bool:
    """
    Windows の UNC 共有パスかどうかを判定する。
    """
    return raw_path.startswith("\\\\") or raw_path.startswith("//")
