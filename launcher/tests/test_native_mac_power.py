"""
macOS ランチャーのスリープ復帰後ホットキー再登録を検証する。
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from launcher_app.ui import native_mac


class FakeNSEvent:
    """
    Cocoa のイベント monitor 登録/解除を記録する。
    """

    removed: list[str] = []

    @staticmethod
    def removeMonitor_(monitor: str) -> None:
        FakeNSEvent.removed.append(monitor)


class FakeNotificationCenter:
    """
    NSWorkspace の通知登録内容を記録する。
    """

    def __init__(self) -> None:
        self.observers: list[tuple[object, str, str, object | None]] = []

    def addObserver_selector_name_object_(self, observer: object, selector: str, name: str, target: object | None) -> None:
        self.observers.append((observer, selector, name, target))


def test_restart_hotkey_monitor_removes_existing_monitors(monkeypatch) -> None:
    """
    復帰時は古い monitor を解除してから新しく登録する。
    """
    FakeNSEvent.removed = []
    monkeypatch.setattr(native_mac, "AppKit", SimpleNamespace(NSEvent=FakeNSEvent))
    delegate = SimpleNamespace(hotkey_monitors=["global", "local"], hotkey_activated=True, started=0)

    def start_hotkey_monitor() -> None:
        delegate.started += 1
        delegate.hotkey_monitors = ["new-global", "new-local"]

    delegate._stop_hotkey_monitor = native_mac.LauncherDelegate._stop_hotkey_monitor.__get__(delegate)
    delegate._start_hotkey_monitor = start_hotkey_monitor
    delegate._restart_hotkey_monitor = native_mac.LauncherDelegate._restart_hotkey_monitor.__get__(delegate)

    delegate._restart_hotkey_monitor()

    assert FakeNSEvent.removed == ["global", "local"]
    assert delegate.hotkey_monitors == ["new-global", "new-local"]
    assert delegate.hotkey_activated is False
    assert delegate.started == 1


def test_power_state_monitor_registers_sleep_and_wake_once(monkeypatch) -> None:
    """
    NSWorkspace の sleep/wake 通知は一度だけ登録する。
    """
    notification_center = FakeNotificationCenter()
    workspace = SimpleNamespace(notificationCenter=lambda: notification_center)
    appkit = SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace),
        NSWorkspaceWillSleepNotification="will-sleep",
        NSWorkspaceDidWakeNotification="did-wake",
    )
    monkeypatch.setattr(native_mac, "AppKit", appkit)
    delegate = SimpleNamespace(power_notifications_registered=False, power_notification_center=None)
    delegate._start_power_state_monitor = native_mac.LauncherDelegate._start_power_state_monitor.__get__(delegate)

    delegate._start_power_state_monitor()
    delegate._start_power_state_monitor()

    assert delegate.power_notification_center is notification_center
    assert delegate.power_notifications_registered is True
    assert notification_center.observers == [
        (delegate, "workspaceWillSleep:", "will-sleep", None),
        (delegate, "workspaceDidWake:", "did-wake", None),
    ]


def test_workspace_wake_restarts_hotkey_monitor(monkeypatch) -> None:
    """
    復帰通知を受け取ったらホットキー monitor を再登録する。
    """
    delegate = native_mac.LauncherDelegate.alloc().init()
    restarted = {"count": 0}

    def restart_hotkey_monitor(self) -> None:
        restarted["count"] += 1

    monkeypatch.setattr(native_mac.LauncherDelegate, "_restart_hotkey_monitor", restart_hotkey_monitor)
    native_mac.LauncherDelegate.workspaceDidWake_(delegate, None)

    assert restarted["count"] == 1
