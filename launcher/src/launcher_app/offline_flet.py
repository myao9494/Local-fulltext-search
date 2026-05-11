"""
Flet デスクトップクライアントをオフライン環境で利用するための準備を行う。
"""

from __future__ import annotations

import os
from pathlib import Path
import platform
import tarfile
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VENDOR_ROOT = PROJECT_ROOT / "launcher" / "vendor" / "flet-view"
CACHE_ROOT = PROJECT_ROOT / "launcher" / ".offline_cache" / "flet-view"


class OfflineFletViewError(RuntimeError):
    """
    オフライン必須モードで Flet View が見つからない場合の起動エラー。
    """


def prepare_flet_view() -> Path | None:
    """
    同梱済みの Flet View を検出し、必要なら展開して FLET_VIEW_PATH を設定する。
    """
    if platform.system() == "Darwin":
        return None
    existing_path = os.environ.get("FLET_VIEW_PATH")
    if existing_path:
        return Path(existing_path)

    platform_name = _platform_name()
    unpacked_dir = VENDOR_ROOT / platform_name
    if _looks_like_flet_view_dir(unpacked_dir):
        os.environ["FLET_VIEW_PATH"] = str(unpacked_dir)
        return unpacked_dir

    archive_path = _find_archive(platform_name)
    if archive_path is not None:
        extracted_dir = CACHE_ROOT / platform_name
        _extract_archive(archive_path, extracted_dir)
        view_dir = _find_flet_view_dir(extracted_dir) or extracted_dir
        os.environ["FLET_VIEW_PATH"] = str(view_dir)
        return view_dir

    if _offline_required():
        raise OfflineFletViewError(_missing_message(platform_name))
    return None


def _platform_name() -> str:
    """
    Flet View 配布物の OS 名をディレクトリ名へ正規化する。
    """
    system_name = platform.system()
    if system_name == "Windows":
        return "windows"
    if system_name == "Linux":
        return "linux"
    return system_name.lower()


def _looks_like_flet_view_dir(path: Path) -> bool:
    """
    FLET_VIEW_PATH として使えるディレクトリかを簡易判定する。
    """
    if not path.is_dir():
        return False
    executable_names = {"flet.exe", "flet", "flet_view.exe", "flet_view"}
    return any((path / name).is_file() for name in executable_names)


def _find_archive(platform_name: str) -> Path | None:
    """
    vendor 配下から対象 OS の Flet View アーカイブを探す。
    """
    if not VENDOR_ROOT.is_dir():
        return None
    patterns = (
        f"flet-view-{platform_name}*.zip",
        f"flet-view-{platform_name}*.tar.gz",
        f"flet-view-{platform_name}*.tgz",
    )
    for pattern in patterns:
        matches = sorted(VENDOR_ROOT.glob(pattern))
        if matches:
            return matches[0]
    return None


def _extract_archive(archive_path: Path, destination: Path) -> None:
    """
    zip/tar.gz の Flet View アーカイブをリポジトリ内キャッシュへ展開する。
    """
    destination.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise OfflineFletViewError(f"不正なパスを含む zip です: {member.filename}")
            archive.extractall(destination)
        return
    if archive_path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path) as archive:
            archive.extractall(destination, filter="data")
        return
    raise OfflineFletViewError(f"未対応の Flet View アーカイブ形式です: {archive_path}")


def _find_flet_view_dir(root: Path) -> Path | None:
    """
    展開後ディレクトリから Flet View 実行ファイルを含む階層を探す。
    """
    if _looks_like_flet_view_dir(root):
        return root
    for path in root.rglob("*"):
        if path.is_dir() and _looks_like_flet_view_dir(path):
            return path
    return None


def _offline_required() -> bool:
    """
    オフライン配布時に Flet View 同梱を必須にするかを返す。
    """
    return os.environ.get("LAUNCHER_REQUIRE_OFFLINE_FLET_VIEW", "").strip().lower() in {"1", "true", "yes", "on"}


def _missing_message(platform_name: str) -> str:
    """
    Flet View 未配置時に表示する復旧手順を返す。
    """
    return (
        "オフライン起動に必要な Flet View が見つかりません。\n"
        f"配置先: {VENDOR_ROOT}\\{platform_name}\\ または "
        f"{VENDOR_ROOT}\\flet-view-{platform_name}.zip\n"
        "オンライン環境で Flet が取得する Flet View アーカイブを保存し、"
        "リポジトリの launcher/vendor/flet-view/ に配置してから再起動してください。"
    )
