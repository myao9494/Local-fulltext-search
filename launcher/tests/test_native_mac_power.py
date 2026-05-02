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


class FakeQuartz:
    """
    CGEventTap の登録/解除を記録する。
    """

    kCGEventTapDisabledByTimeout = -2
    kCGEventFlagsChanged = 12
    kCGHIDEventTap = 0
    kCGSessionEventTap = 1
    kCGHeadInsertEventTap = 0
    kCGEventTapOptionListenOnly = 1
    kCFRunLoopCommonModes = "common"
    added: list[tuple[str, str]] = []
    enabled: list[tuple[str, bool]] = []
    invalidated: list[str] = []
    removed: list[tuple[str, str]] = []
    created_locations: list[int] = []
    unavailable_locations: set[int] = set()
    callback = None

    @staticmethod
    def CGEventMaskBit(event_type: int) -> int:
        return 1 << event_type

    @staticmethod
    def CGEventTapCreate(tap: int, place: int, options: int, mask: int, callback, refcon: object | None) -> str:
        FakeQuartz.created_locations.append(tap)
        if tap in FakeQuartz.unavailable_locations:
            return None
        FakeQuartz.callback = callback
        return f"event-tap-{tap}"

    @staticmethod
    def CFMachPortCreateRunLoopSource(allocator: object | None, event_tap: str, order: int) -> str:
        return "event-source"

    @staticmethod
    def CFRunLoopGetCurrent() -> str:
        return "run-loop"

    @staticmethod
    def CFRunLoopAddSource(run_loop: str, source: str, mode: str) -> None:
        FakeQuartz.added.append((source, mode))

    @staticmethod
    def CGEventTapEnable(event_tap: str, enabled: bool) -> None:
        FakeQuartz.enabled.append((event_tap, enabled))

    @staticmethod
    def CFRunLoopRemoveSource(run_loop: str, source: str, mode: str) -> None:
        FakeQuartz.removed.append((source, mode))

    @staticmethod
    def CFMachPortInvalidate(event_tap: str) -> None:
        FakeQuartz.invalidated.append(event_tap)


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
    FakeQuartz.removed = []
    FakeQuartz.invalidated = []
    monkeypatch.setattr(native_mac, "AppKit", SimpleNamespace(NSEvent=FakeNSEvent))
    monkeypatch.setattr(native_mac, "Quartz", FakeQuartz)
    delegate = SimpleNamespace(hotkey_monitors=["global", "local"], hotkey_activated=True, started=0)
    delegate.hotkey_event_tap = "event-tap"
    delegate.hotkey_event_tap_location = FakeQuartz.kCGHIDEventTap
    delegate.hotkey_event_tap_source = "event-source"
    delegate.hotkey_event_tap_callback = object()

    def start_hotkey_monitor() -> None:
        delegate.started += 1
        delegate.hotkey_monitors = ["new-global", "new-local"]

    delegate._stop_hotkey_monitor = native_mac.LauncherDelegate._stop_hotkey_monitor.__get__(delegate)
    delegate._start_hotkey_monitor = start_hotkey_monitor
    delegate._restart_hotkey_monitor = native_mac.LauncherDelegate._restart_hotkey_monitor.__get__(delegate)

    delegate._restart_hotkey_monitor()

    assert FakeNSEvent.removed == ["global", "local"]
    assert FakeQuartz.removed == [("event-source", "common")]
    assert FakeQuartz.invalidated == ["event-tap"]
    assert delegate.hotkey_monitors == ["new-global", "new-local"]
    assert delegate.hotkey_event_tap is None
    assert delegate.hotkey_event_tap_location is None
    assert delegate.hotkey_event_tap_source is None
    assert delegate.hotkey_event_tap_callback is None
    assert delegate.hotkey_activated is False
    assert delegate.started == 1


def test_start_hotkey_event_tap_registers_session_flags_monitor(monkeypatch) -> None:
    """
    CGEventTap で HID レベルの flagsChanged を優先監視する。
    """
    FakeQuartz.added = []
    FakeQuartz.enabled = []
    FakeQuartz.created_locations = []
    FakeQuartz.unavailable_locations = set()
    FakeQuartz.callback = None
    monkeypatch.setattr(native_mac, "Quartz", FakeQuartz)
    delegate = SimpleNamespace(
        hotkey_event_tap=None,
        hotkey_event_tap_location=None,
        hotkey_event_tap_source=None,
        hotkey_event_tap_callback=None,
    )
    delegate._start_hotkey_event_tap = native_mac.LauncherDelegate._start_hotkey_event_tap.__get__(delegate)

    delegate._start_hotkey_event_tap()

    assert delegate.hotkey_event_tap == "event-tap-0"
    assert delegate.hotkey_event_tap_location == FakeQuartz.kCGHIDEventTap
    assert delegate.hotkey_event_tap_source == "event-source"
    assert delegate.hotkey_event_tap_callback is FakeQuartz.callback
    assert FakeQuartz.created_locations == [FakeQuartz.kCGHIDEventTap]
    assert FakeQuartz.added == [("event-source", "common")]
    assert FakeQuartz.enabled == [("event-tap-0", True)]


def test_start_hotkey_event_tap_falls_back_to_session_when_hid_is_unavailable(monkeypatch) -> None:
    """
    HID tap を作れない場合だけ session tap にフォールバックする。
    """
    FakeQuartz.added = []
    FakeQuartz.enabled = []
    FakeQuartz.created_locations = []
    FakeQuartz.unavailable_locations = {FakeQuartz.kCGHIDEventTap}
    FakeQuartz.callback = None
    monkeypatch.setattr(native_mac, "Quartz", FakeQuartz)
    delegate = SimpleNamespace(
        hotkey_event_tap=None,
        hotkey_event_tap_location=None,
        hotkey_event_tap_source=None,
        hotkey_event_tap_callback=None,
    )
    delegate._start_hotkey_event_tap = native_mac.LauncherDelegate._start_hotkey_event_tap.__get__(delegate)

    delegate._start_hotkey_event_tap()

    assert delegate.hotkey_event_tap == "event-tap-1"
    assert delegate.hotkey_event_tap_location == FakeQuartz.kCGSessionEventTap
    assert FakeQuartz.created_locations == [FakeQuartz.kCGHIDEventTap, FakeQuartz.kCGSessionEventTap]


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
