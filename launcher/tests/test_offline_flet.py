"""
Flet View のオフライン同梱検出と環境変数設定を検証する。
"""

from pathlib import Path
import zipfile

import pytest

from launcher_app import offline_flet
from launcher_app.offline_flet import OfflineFletViewError, prepare_flet_view


def test_prepare_flet_view_uses_existing_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    FLET_VIEW_PATH が既に指定されている場合は同梱物を探さずその値を使う。
    """
    view_path = tmp_path / "custom-view"
    monkeypatch.setenv("FLET_VIEW_PATH", str(view_path))
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")

    assert prepare_flet_view() == view_path


def test_prepare_flet_view_sets_unpacked_vendor_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    launcher/vendor/flet-view/windows に実行ファイルがあれば FLET_VIEW_PATH に設定する。
    """
    vendor_root = tmp_path / "vendor" / "flet-view"
    windows_dir = vendor_root / "windows"
    windows_dir.mkdir(parents=True)
    (windows_dir / "flet.exe").write_text("", encoding="utf-8")
    monkeypatch.delenv("FLET_VIEW_PATH", raising=False)
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline_flet, "VENDOR_ROOT", vendor_root)

    assert prepare_flet_view() == windows_dir
    assert offline_flet.os.environ["FLET_VIEW_PATH"] == str(windows_dir)


def test_prepare_flet_view_extracts_vendor_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    zip アーカイブだけが配置されている場合はキャッシュへ展開して FLET_VIEW_PATH を設定する。
    """
    vendor_root = tmp_path / "vendor" / "flet-view"
    cache_root = tmp_path / "cache" / "flet-view"
    vendor_root.mkdir(parents=True)
    archive_path = vendor_root / "flet-view-windows.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Release/flet.exe", "")
    monkeypatch.delenv("FLET_VIEW_PATH", raising=False)
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline_flet, "VENDOR_ROOT", vendor_root)
    monkeypatch.setattr(offline_flet, "CACHE_ROOT", cache_root)

    view_path = prepare_flet_view()

    assert view_path == cache_root / "windows" / "Release"
    assert offline_flet.os.environ["FLET_VIEW_PATH"] == str(view_path)


def test_prepare_flet_view_reuses_cached_archive_extract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    既に展開済みの Flet View がある場合は再展開せず、Windows の DLL ロックを避ける。
    """
    vendor_root = tmp_path / "vendor" / "flet-view"
    cache_root = tmp_path / "cache" / "flet-view"
    cached_view = cache_root / "windows" / "flet"
    vendor_root.mkdir(parents=True)
    cached_view.mkdir(parents=True)
    archive_path = vendor_root / "flet-view-windows.zip"
    (cached_view / "flet.exe").write_text("", encoding="utf-8")
    locked_plugin = cached_view / "audioplayers_windows_plugin.dll"
    locked_plugin.write_text("in use", encoding="utf-8")
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("flet/flet.exe", "")
        archive.writestr("flet/audioplayers_windows_plugin.dll", "replacement")
    monkeypatch.delenv("FLET_VIEW_PATH", raising=False)
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline_flet, "VENDOR_ROOT", vendor_root)
    monkeypatch.setattr(offline_flet, "CACHE_ROOT", cache_root)

    view_path = prepare_flet_view()

    assert view_path == cached_view
    assert locked_plugin.read_text(encoding="utf-8") == "in use"


def test_prepare_flet_view_ignores_directory_named_like_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    flet/ ディレクトリを実行ファイルと誤認せず、その中の flet.exe 階層を使う。
    """
    vendor_root = tmp_path / "vendor" / "flet-view"
    cache_root = tmp_path / "cache" / "flet-view"
    vendor_root.mkdir(parents=True)
    archive_path = vendor_root / "flet-view-windows.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("flet/flet.exe", "")
    monkeypatch.delenv("FLET_VIEW_PATH", raising=False)
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline_flet, "VENDOR_ROOT", vendor_root)
    monkeypatch.setattr(offline_flet, "CACHE_ROOT", cache_root)

    view_path = prepare_flet_view()

    assert view_path == cache_root / "windows" / "flet"
    assert offline_flet.os.environ["FLET_VIEW_PATH"] == str(view_path)


def test_prepare_flet_view_raises_when_offline_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    オフライン必須モードで同梱物がない場合は Flet のダウンロードへ進む前に止める。
    """
    monkeypatch.delenv("FLET_VIEW_PATH", raising=False)
    monkeypatch.setenv("LAUNCHER_REQUIRE_OFFLINE_FLET_VIEW", "1")
    monkeypatch.setattr(offline_flet.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline_flet, "VENDOR_ROOT", tmp_path / "missing")

    with pytest.raises(OfflineFletViewError, match="Flet View"):
        prepare_flet_view()
