"""
フォルダ選択 API の OS 別ダイアログ起動処理を検証する。
Windows では親ウィンドウを一時的に最前面化し、ダイアログが背面に隠れにくいことを担保する。
"""

from __future__ import annotations

import subprocess

import pytest
from fastapi import HTTPException

from app.api.folders import _pick_folder_windows


def test_pick_folder_windows_requests_topmost_owner_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Windows では一時的な最前面フォームを親にしてダイアログを開く。
    """
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="C:\\Users\\mine\\Documents", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    selected = _pick_folder_windows()

    assert selected == "C:\\Users\\mine\\Documents"
    assert captured["command"][:2] == ["powershell", "-NoProfile"]
    script = captured["command"][3]
    assert "$owner.TopMost = $true;" in script
    assert "$owner.Opacity = 0;" in script
    assert "$owner.ShowInTaskbar = $false;" in script
    assert "$owner.Show();" in script
    assert "$owner.Activate();" in script
    assert "$owner.BringToFront();" in script
    assert "$dialog.ShowDialog($owner)" in script


def test_pick_folder_windows_raises_cancelled_when_no_path_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Windows で選択結果が空ならキャンセル扱いにする。
    """

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HTTPException) as error_info:
        _pick_folder_windows()

    assert error_info.value.status_code == 400
    assert error_info.value.detail == "Folder selection was cancelled."
