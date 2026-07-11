"""外部8001 Openハブをこのリポジトリが管理しない契約を固定する。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_windows_start_script_only_releases_search_api_port() -> None:
    """Windows起動スクリプトは外部8001プロセスを停止対象に含めない。"""
    script = (PROJECT_ROOT / "start_windows.bat").read_text(encoding="utf-8")

    assert "Get-NetTCPConnection -LocalPort ([int]$env:SEARCH_APP_PORT)" in script
    assert "SEARCH_APP_OPEN_HUB" not in script
    assert "@([int]$env:SEARCH_APP_PORT, 8001)" not in script


def test_backend_does_not_implement_or_manage_open_hub() -> None:
    """8001サーバー・管理API・プロセスマネージャーを再導入しない。"""
    assert not (PROJECT_ROOT / "backend" / "app" / "open_hub.py").exists()
    assert not (PROJECT_ROOT / "backend" / "app" / "api" / "open_hub.py").exists()
    assert not (PROJECT_ROOT / "backend" / "app" / "services" / "open_hub_service.py").exists()


def test_clients_keep_existing_external_open_paths() -> None:
    """Webとランチャーは既存8001のpath規則だけを保持する。"""
    launcher_urls = (PROJECT_ROOT / "launcher" / "src" / "launcher_app" / "ui" / "urls.py").read_text(encoding="utf-8")
    results_list = (PROJECT_ROOT / "frontend" / "src" / "components" / "ResultsList.tsx").read_text(encoding="utf-8")

    assert "/api/fullpath?path=" in launcher_urls
    assert "/?path=" in launcher_urls
    assert "/api/fullpath?path=" in results_list
    assert "/?path=" in results_list
