"""
ランチャーが OS 標準アプリでファイルやフォルダを開くコマンドを検証する。
"""

import subprocess

import pytest

from launcher_app.services.file_actions import FileActionError, open_path, reveal_path


def test_open_path_uses_macos_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    macOS では対象パスを open コマンドで直接開く。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    open_path("/tmp/docs/a.md")

    assert captured["command"] == ["/usr/bin/open", "/tmp/docs/a.md"]


def test_reveal_path_uses_macos_finder_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    macOS では Finder 上で対象ファイルを選択表示する。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    reveal_path("/tmp/docs/a.md")

    assert captured["command"] == ["/usr/bin/open", "-R", "/tmp/docs/a.md"]


def test_windows_reveal_selects_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Windows ではファイルを Explorer の選択表示で開く。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("os.path.isdir", lambda path: False)
    monkeypatch.setattr(subprocess, "run", fake_run)

    reveal_path("C:/docs/a.md")

    assert captured["command"] == ["explorer.exe", "/select,", "C:\\docs\\a.md"]


def test_open_path_raises_when_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    OS コマンド失敗時はランチャー向け例外へ変換する。
    """
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FileActionError, match="failed"):
        open_path("/tmp/docs/a.md")
