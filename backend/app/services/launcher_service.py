"""
デスクトップランチャープロセスの起動・停止・再起動・ログ取得を管理する。
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Literal

from app.config import PROJECT_ROOT_DIR, settings


LauncherStatus = Literal["running", "stopped", "exited"]


class LauncherManager:
    """
    FastAPI プロセス配下でランチャーを子プロセスとして管理する。
    """

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.log_path = settings.launcher_log_path
        self.launcher_src = PROJECT_ROOT_DIR / "launcher" / "src"
        self.python_executable = _resolve_launcher_python()

    def autostart_if_enabled(self) -> None:
        """
        設定が有効な場合だけランチャーを起動する。
        """
        if settings.launcher_autostart:
            self.start()

    def start(self) -> dict[str, object]:
        """
        未起動ならランチャーを起動し、現在状態を返す。
        """
        if self.is_running():
            return self.status()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{self.launcher_src}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(self.launcher_src)
        env.setdefault("LAUNCHER_API_BASE_URL", f"http://127.0.0.1:{settings.bind_port}")
        env.setdefault("LAUNCHER_WEB_BASE_URL", f"http://127.0.0.1:{settings.bind_port}")
        command = [self.python_executable, "-m", "launcher_app.main"]
        log_file = self.log_path.open("a", encoding="utf-8")
        log_file.write(f"\n--- launcher start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_file.flush()
        self.process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT_DIR),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_file.close()
        return self.status()

    def stop(self) -> dict[str, object]:
        """
        起動中のランチャーへ終了要求を送り、短時間待ってから状態を返す。
        """
        if not self.is_running():
            return self.status()
        assert self.process is not None
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        return self.status()

    def restart(self) -> dict[str, object]:
        """
        ランチャーを停止してから再起動する。
        """
        self.stop()
        return self.start()

    def is_running(self) -> bool:
        """
        子プロセスが生存しているかを返す。
        """
        return self.process is not None and self.process.poll() is None

    def status(self) -> dict[str, object]:
        """
        UI 表示用の状態とログ末尾を返す。
        """
        returncode = self.process.poll() if self.process is not None else None
        status: LauncherStatus
        if self.is_running():
            status = "running"
        elif self.process is None:
            status = "stopped"
        else:
            status = "exited"
        return {
            "status": status,
            "is_running": status == "running",
            "pid": self.process.pid if self.process is not None and status == "running" else None,
            "returncode": returncode,
            "autostart": settings.launcher_autostart,
            "log_path": str(self.log_path),
            "logs": self.read_logs(),
        }

    def read_logs(self, *, max_lines: int = 200) -> list[str]:
        """
        ランチャーログの末尾を返す。
        """
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]


def _resolve_launcher_python() -> str:
    """
    ランチャー依存が入るプロジェクトルート .venv の Python を優先する。
    """
    candidate = PROJECT_ROOT_DIR / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    windows_candidate = PROJECT_ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if windows_candidate.exists():
        return str(windows_candidate)
    return sys.executable
