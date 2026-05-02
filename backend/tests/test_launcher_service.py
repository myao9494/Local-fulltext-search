"""
ランチャープロセス管理サービスの起動・停止・ログ取得を検証する。
"""

import subprocess

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

    manager = LauncherManager()
    manager.log_path = tmp_path / "launcher.log"
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    status = manager.start()

    assert status["is_running"] is True
    assert captured["command"][-2:] == ["-m", "launcher_app.main"]
    assert str(captured["command"][0]).endswith("python") or str(captured["command"][0]).endswith("python.exe")
    assert "PYTHONPATH" in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["LAUNCHER_WEB_BASE_URL"] == "http://127.0.0.1:8079"


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
