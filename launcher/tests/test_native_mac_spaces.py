"""
macOS ランチャーを現在の仮想デスクトップへ表示するための処理を検証する。
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from launcher_app.ui import native_mac


class FakePanel:
    """
    NSPanel に設定された表示属性を記録する。
    """

    def __init__(self, *, miniaturized: bool = False) -> None:
        self.behavior = None
        self.level = None
        self.hides_on_deactivate = None
        self.miniaturized = miniaturized
        self.deminiaturized = False

    def setCollectionBehavior_(self, behavior: int) -> None:
        self.behavior = behavior

    def setLevel_(self, level: int) -> None:
        self.level = level

    def setHidesOnDeactivate_(self, enabled: bool) -> None:
        self.hides_on_deactivate = enabled

    def isMiniaturized(self) -> bool:
        return self.miniaturized

    def deminiaturize_(self, sender: object | None) -> None:
        self.deminiaturized = True


class FakeProcessInfo:
    """
    App Nap 抑止 activity の開始を記録する。
    """

    def __init__(self) -> None:
        self.started: list[tuple[int, str]] = []

    def beginActivityWithOptions_reason_(self, options: int, reason: str) -> str:
        self.started.append((options, reason))
        return "activity-token"


def test_prepare_panel_for_active_space_reapplies_window_behavior(monkeypatch) -> None:
    """
    表示直前に Space 関連の window behavior と level を張り直す。
    """
    appkit = SimpleNamespace(
        NSWindowCollectionBehaviorCanJoinAllSpaces=1,
        NSWindowCollectionBehaviorFullScreenAuxiliary=2,
        NSWindowCollectionBehaviorStationary=4,
        NSWindowCollectionBehaviorTransient=8,
        NSStatusWindowLevel=99,
    )
    monkeypatch.setattr(native_mac, "AppKit", appkit)
    panel = FakePanel(miniaturized=True)
    delegate = SimpleNamespace(panel=panel)
    delegate._panel_collection_behavior = native_mac.LauncherDelegate._panel_collection_behavior.__get__(delegate)
    delegate._prepare_panel_for_active_space = native_mac.LauncherDelegate._prepare_panel_for_active_space.__get__(delegate)

    delegate._prepare_panel_for_active_space()

    assert panel.behavior == 15
    assert panel.level == 99
    assert panel.hides_on_deactivate is False
    assert panel.deminiaturized is True


def test_begin_activity_starts_app_nap_prevention_once(monkeypatch) -> None:
    """
    常駐ランチャー用の App Nap 抑止 activity は一度だけ開始する。
    """
    process_info = FakeProcessInfo()
    appkit = SimpleNamespace(
        NSActivityUserInitiatedAllowingIdleSystemSleep=16,
        NSActivityLatencyCritical=32,
        NSProcessInfo=SimpleNamespace(processInfo=lambda: process_info),
    )
    monkeypatch.setattr(native_mac, "AppKit", appkit)
    delegate = SimpleNamespace(activity_token=None)
    delegate._begin_activity = native_mac.LauncherDelegate._begin_activity.__get__(delegate)

    delegate._begin_activity()
    delegate._begin_activity()

    assert delegate.activity_token == "activity-token"
    assert process_info.started == [(48, "Local Fulltext Search launcher hotkey monitor")]
