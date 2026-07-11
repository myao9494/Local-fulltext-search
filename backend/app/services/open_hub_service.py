"""
8001番Open/UIハブの子プロセスを起動・停止・監視する。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Literal

from app.config import BACKEND_DIR, settings

OpenHubStatus = Literal["running", "stopped", "exited"]


class OpenHubManager:
    """Openハブをバックエンドとは別プロセスで管理する。"""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.log_path = settings.open_hub_log_path
        self.last_error: str | None = None

    def autostart_if_enabled(self) -> None:
        if settings.open_hub_autostart:
            self.start()

    def start(self) -> dict[str, object]:
        if self.is_running():
            return self.status()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.setdefault("SEARCH_APP_OPEN_HUB_HOST", settings.open_hub_host)
        env.setdefault("SEARCH_APP_OPEN_HUB_PORT", str(settings.open_hub_port))
        env.setdefault("SEARCH_APP_OPEN_HUB_API_BASE_URL", f"http://127.0.0.1:{settings.bind_port}")
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n--- open hub start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            log_file.flush()
            try:
                self.process = subprocess.Popen(
                    [sys.executable, "-m", "app.open_hub"],
                    cwd=str(BACKEND_DIR),
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.last_error = None
            except (OSError, subprocess.SubprocessError) as error:
                self.process = None
                self.last_error = f"Open hub process could not be started: {error}"
                log_file.write(f"{self.last_error}\n")
        return self.status()

    def stop(self) -> dict[str, object]:
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

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def status(self) -> dict[str, object]:
        if self.is_running():
            state: OpenHubStatus = "running"
        elif self.process is None:
            state = "stopped"
        else:
            state = "exited"
        return {
            "status": state,
            "is_running": state == "running",
            "pid": self.process.pid if self.process is not None and state == "running" else None,
            "returncode": self.process.poll() if self.process is not None else None,
            "last_error": self.last_error,
            "port": settings.open_hub_port,
            "api_base_url": os.getenv("SEARCH_APP_OPEN_HUB_API_BASE_URL", f"http://127.0.0.1:{settings.bind_port}"),
            "log_path": str(self.log_path),
        }
