r"""
Windows の UNC パスと通常パスの正規化、および子孫パス検索用の境界計算を扱う。
`\\server\share\...` 形式は共有名を壊さずに保持し、検索用文字列では POSIX 風区切りへそろえる。
"""

from pathlib import Path, PureWindowsPath


class AbsolutePathRequiredError(ValueError):
    """
    検索・インデックス対象に相対パスが渡されたことを表す。
    """


def normalize_path(raw_path: str | Path) -> Path:
    """
    実ファイルアクセス向けの Path を返す。
    Windows の UNC パスは `resolve()` で壊さないよう、そのまま `Path` として扱う。
    """
    raw_value = str(raw_path)
    if _is_windows_unc_path(raw_value):
        return Path(raw_value).expanduser()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise AbsolutePathRequiredError("Absolute path is required.")
    return candidate.resolve()


def normalize_path_str(raw_path: str | Path) -> str:
    """
    DB 保存や検索比較用に、Windows の UNC パスを `//server/share/...` 形式へ正規化する。
    """
    raw_value = str(raw_path)
    if _is_windows_unc_path(raw_value):
        return PureWindowsPath(raw_value).as_posix()
    return normalize_path(raw_path).as_posix()


def get_descendant_path_prefix(root_path: str) -> str:
    """
    あるディレクトリ配下の子孫パスに限定するための前方一致接頭辞を返す。
    ルートディレクトリでは `/` や `C:/` を二重スラッシュ化しない。
    """
    return root_path if root_path.endswith("/") else f"{root_path}/"


def get_descendant_path_range(root_path: str) -> tuple[str, str]:
    """
    子孫パスの前方一致を B-tree 範囲検索へ変換する。
    接頭辞に最大コードポイントを連結し、root パスでも壊れない上限を作る。
    """
    prefix = get_descendant_path_prefix(root_path)
    return prefix, f"{prefix}{chr(0x10FFFF)}"


def get_relative_path(root_path: Path, target_path: Path) -> Path:
    return target_path.relative_to(root_path)


def get_depth(relative_path: Path) -> int:
    return len(relative_path.parts) - 1


def _is_windows_unc_path(raw_path: str) -> bool:
    """
    Windows の UNC 共有パスかどうかを判定する。
    """
    return raw_path.startswith("\\\\") or raw_path.startswith("//")
