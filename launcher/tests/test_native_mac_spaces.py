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


def test_launcher_panel_key_down_submits_memo_on_focus(monkeypatch) -> None:
    """
    送信ボタンにフォーカスがある状態で Return キーが押された場合、gantt 追加処理が実行されることを検証する。
    """
    import AppKit
    panel = native_mac.LauncherPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 100, 100),
        AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered,
        False
    )
    
    class FakeDelegate:
        def __init__(self) -> None:
            self.memo_submit_button = "submit_btn"
            self.memo_cancel_button = "cancel_btn"
            self.submitted = False
            self.screen = None
            
        def _submit_memo(self) -> None:
            self.submitted = True
            
        def _switch_screen(self, screen: str) -> None:
            self.screen = screen
            
    delegate = FakeDelegate()
    panel.setDelegate_(delegate)
    
    monkeypatch.setattr(panel, "firstResponder", lambda: delegate.memo_submit_button)
    
    # super() 呼び出しのモック
    super_called = []
    monkeypatch.setattr(native_mac, "objc", SimpleNamespace(
        super=lambda cls, self: SimpleNamespace(keyDown_=lambda ev: super_called.append(True))
    ))
    
    # 本物のキーイベントを作成 (\r)
    event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
        AppKit.NSEventTypeKeyDown,
        AppKit.NSMakePoint(0, 0),
        0,
        0.0,
        0,
        None,
        "\r",
        "\r",
        False,
        36
    )
    
    panel.keyDown_(event)
    
    assert delegate.submitted is True
    assert len(super_called) == 0


def test_launcher_panel_key_down_switches_to_search_on_cancel_focus(monkeypatch) -> None:
    """
    キャンセルボタンにフォーカスがある状態で Return キーが押された場合、検索画面へ戻る処理が実行されることを検証する。
    """
    import AppKit
    panel = native_mac.LauncherPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 100, 100),
        AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered,
        False
    )
    
    class FakeDelegate:
        def __init__(self) -> None:
            self.memo_submit_button = "submit_btn"
            self.memo_cancel_button = "cancel_btn"
            self.submitted = False
            self.screen = None
            
        def _submit_memo(self) -> None:
            self.submitted = True
            
        def _switch_screen(self, screen: str) -> None:
            self.screen = screen
            
    delegate = FakeDelegate()
    panel.setDelegate_(delegate)
    
    monkeypatch.setattr(panel, "firstResponder", lambda: delegate.memo_cancel_button)
    
    # super() 呼び出しのモック
    super_called = []
    monkeypatch.setattr(native_mac, "objc", SimpleNamespace(
        super=lambda cls, self: SimpleNamespace(keyDown_=lambda ev: super_called.append(True))
    ))
    
    # 本物のキーイベントを作成 (\n)
    event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
        AppKit.NSEventTypeKeyDown,
        AppKit.NSMakePoint(0, 0),
        0,
        0.0,
        0,
        None,
        "\n",
        "\n",
        False,
        36
    )
    
    panel.keyDown_(event)
    
    assert delegate.screen == "search"
    assert len(super_called) == 0


def test_launcher_panel_key_down_falls_back_for_other_keys(monkeypatch) -> None:
    """
    Return/Enter 以外のキーや他のフォーカス状態では、親クラス (super) の keyDown_ にフォールバックすることを検証する。
    """
    import AppKit
    panel = native_mac.LauncherPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 100, 100),
        AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered,
        False
    )
    
    class FakeDelegate:
        def __init__(self) -> None:
            self.memo_submit_button = "submit_btn"
            self.memo_cancel_button = "cancel_btn"
            self.submitted = False
            self.screen = None
            
        def _submit_memo(self) -> None:
            self.submitted = True
            
        def _switch_screen(self, screen: str) -> None:
            self.screen = screen
            
    delegate = FakeDelegate()
    panel.setDelegate_(delegate)
    
    monkeypatch.setattr(panel, "firstResponder", lambda: delegate.memo_submit_button)
    
    # super() 呼び出しのモック
    super_called = []
    monkeypatch.setattr(native_mac, "objc", SimpleNamespace(
        super=lambda cls, self: SimpleNamespace(keyDown_=lambda ev: super_called.append(True))
    ))
    
    # 本物のキーイベントを作成 ("a")
    event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
        AppKit.NSEventTypeKeyDown,
        AppKit.NSMakePoint(0, 0),
        0,
        0.0,
        0,
        None,
        "a",
        "a",
        False,
        0
    )
    
    panel.keyDown_(event)
    
    assert delegate.submitted is False
    assert delegate.screen is None
    assert super_called == [True]

