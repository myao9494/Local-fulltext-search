"""
ランチャープロセス管理サービスの起動・停止・ログ取得を検証する。
"""

import subprocess
from pathlib import Path

from app.services import launcher_service
from app.services.launcher_service import LauncherManager


class FakeProcess:
    """
    subprocess.Popen の代わりに利用する最小プロセススタブ。
    """

    def __init__(self, pid: int = 1234) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_launcher_manager_starts_process(monkeypatch, tmp_path) -> None:
    """
    start は launcher_app.main を PYTHONPATH 付きで起動する。
    """
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    manager = LauncherManager(wpf_resolver=lambda: None)
    manager.log_path = tmp_path / "launcher.log"
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    status = manager.start()

    assert status["is_running"] is True
    assert captured["command"][-2:] == ["-m", "launcher_app.main"]
    assert str(captured["command"][0]).endswith("python") or str(captured["command"][0]).endswith("python.exe")
    assert "PYTHONPATH" in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["LAUNCHER_WEB_BASE_URL"] == "http://127.0.0.1:8001"


def test_launcher_manager_prefers_published_wpf_executable(monkeypatch, tmp_path) -> None:
    """
    発行済みWPF版が選択済みならPython/FletではなくEXEを直接起動する。
    """
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return FakeProcess()

    manager = LauncherManager(wpf_resolver=lambda: Path(r"C:\launcher\LocalSearchLauncher.exe"))
    manager.log_path = tmp_path / "launcher.log"
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    status = manager.start()

    assert status["is_running"] is True
    assert captured["command"] == [r"C:\launcher\LocalSearchLauncher.exe"]


def test_launcher_manager_redetects_wpf_on_each_start(monkeypatch, tmp_path) -> None:
    """
    バックエンド起動後にWPFを配置しても、次の開始操作でEXEを再検出する。
    """
    detected: list[Path | None] = [None, Path(r"C:\launcher\LocalSearchLauncher.exe")]
    captured: dict[str, object] = {}

    def resolve() -> Path | None:
        return detected.pop(0)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return FakeProcess()

    manager = LauncherManager(wpf_resolver=resolve)
    manager.log_path = tmp_path / "launcher.log"
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    manager.start()

    assert captured["command"] == [r"C:\launcher\LocalSearchLauncher.exe"]


def test_resolve_wpf_launcher_prefers_folder_distribution(monkeypatch, tmp_path) -> None:
    """
    Windowsの自動検出は通常版をsingle-file版より優先する。
    """
    folder_exe = tmp_path / "launcher" / "windows" / "publish" / "folder" / "LocalSearchLauncher.exe"
    single_exe = tmp_path / "launcher" / "windows" / "publish" / "single-file" / "LocalSearchLauncher.exe"
    folder_exe.parent.mkdir(parents=True)
    single_exe.parent.mkdir(parents=True)
    folder_exe.touch()
    single_exe.touch()
    monkeypatch.setattr(launcher_service.sys, "platform", "win32")
    monkeypatch.setattr(launcher_service, "PROJECT_ROOT_DIR", tmp_path)
    monkeypatch.delenv("SEARCH_APP_WPF_LAUNCHER_PATH", raising=False)

    assert launcher_service._resolve_wpf_launcher() == folder_exe.resolve()


def test_resolve_wpf_launcher_prefers_explicit_path(monkeypatch, tmp_path) -> None:
    """
    環境変数で指定した配布先はリポジトリ内の自動検出より優先する。
    """
    explicit_exe = tmp_path / "company-distribution" / "LocalSearchLauncher.exe"
    explicit_exe.parent.mkdir(parents=True)
    explicit_exe.touch()
    monkeypatch.setattr(launcher_service.sys, "platform", "win32")
    monkeypatch.setenv("SEARCH_APP_WPF_LAUNCHER_PATH", str(explicit_exe))

    assert launcher_service._resolve_wpf_launcher() == explicit_exe.resolve()


def test_launcher_manager_stop_terminates_process(tmp_path) -> None:
    """
    stop は起動中プロセスへ terminate を送る。
    """
    manager = LauncherManager()
    manager.log_path = tmp_path / "launcher.log"
    process = FakeProcess()
    manager.process = process

    status = manager.stop()

    assert process.terminated is True
    assert status["is_running"] is False


def test_launcher_manager_reads_log_tail(tmp_path) -> None:
    """
    read_logs はログ末尾だけを返す。
    """
    manager = LauncherManager()
    manager.log_path = tmp_path / "launcher.log"
    manager.log_path.write_text("\n".join(f"line {index}" for index in range(5)), encoding="utf-8")

    assert manager.read_logs(max_lines=2) == ["line 3", "line 4"]


def test_launcher_spawn_failure_is_reported_without_crashing_backend(monkeypatch, tmp_path) -> None:
    """EXE起動失敗はバックエンド全体を落とさず管理状態とログへ残す。"""
    manager = LauncherManager(wpf_resolver=lambda: Path(r"C:\missing\LocalSearchLauncher.exe"))
    manager.log_path = tmp_path / "launcher.log"
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")))

    result = manager.start()

    assert result["is_running"] is False
    assert "blocked" in str(result["last_error"])
    assert "blocked" in manager.log_path.read_text(encoding="utf-8")
