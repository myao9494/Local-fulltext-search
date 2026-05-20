"""
グローバルホットキー定義が OS ごとの仕様に合うことを検証する。
"""

from typing import Any

from launcher_app.services.hotkeys import (
    GlobalHotkeyController,
    ModifierChordState,
    hotkey_spec_for_platform,
    modifier_names_for_platform,
)


class StubKey:
    """
    pynput の Key.name 相当だけを持つテスト用キー。
    """

    def __init__(self, name: str) -> None:
        self.name = name


def test_hotkey_spec_for_macos() -> None:
    """
    macOS では Command + Option を表示名として返す。
    """
    assert hotkey_spec_for_platform("Darwin") == "Command + Option"
    assert modifier_names_for_platform("Darwin") == frozenset({"cmd", "alt"})


def test_hotkey_spec_for_windows() -> None:
    """
    Windows では Windows + Alt を表示名として返す。
    """
    assert hotkey_spec_for_platform("Windows") == "Windows + Alt"
    assert modifier_names_for_platform("Windows") == frozenset({"cmd", "alt"})


def test_hotkey_spec_for_linux() -> None:
    """
    Linux では Ctrl + Shift を表示名として返す。
    """
    assert hotkey_spec_for_platform("Linux") == "Ctrl + Shift"
    assert modifier_names_for_platform("Linux") == frozenset({"ctrl", "shift"})


def test_modifier_chord_activates_once_until_release() -> None:
    """
    修飾キーだけの組み合わせは揃った瞬間だけ発火し、解除後に再発火できる。
    """
    state = ModifierChordState(frozenset({"cmd", "shift"}))

    assert state.press("cmd") is False
    assert state.press("shift") is True
    assert state.press("shift") is False

    state.release("cmd")
    assert state.press("cmd") is True


def test_modifier_chord_does_not_keep_stale_windows_key_after_activation() -> None:
    """
    Windows キーの release を取りこぼしても、次の Alt 単独押下で再発火しない。
    """
    state = ModifierChordState(frozenset({"cmd", "alt"}))

    assert state.press("cmd") is False
    assert state.press("alt") is True

    state.release("alt")
    assert state.press("alt") is False


def test_modifier_chord_ignores_stale_windows_key_before_activation() -> None:
    """
    Windows キーの押下状態だけが古く残っても、後から Alt 単独で発火しない。
    """
    now = 100.0
    state = ModifierChordState(frozenset({"cmd", "alt"}), now=lambda: now, max_chord_seconds=1.0)

    assert state.press("cmd") is False
    now = 102.0

    assert state.press("alt") is False


def test_global_hotkey_does_not_activate_when_required_modifiers_are_not_physically_down() -> None:
    """
    イベント履歴上は Win+Alt が揃っても、実キー状態が揃わなければ発火しない。
    """
    activated: list[bool] = []
    controller = GlobalHotkeyController(
        lambda: activated.append(True),
        required_modifiers=frozenset({"cmd", "alt"}),
        modifier_state_verifier=lambda required: False,
    )

    controller._on_press(StubKey("cmd"))
    controller._on_press(StubKey("alt"))

    assert activated == []


def test_global_hotkey_activates_when_required_modifiers_are_physically_down() -> None:
    """
    Win+Alt のイベントと実キー状態がどちらも揃った場合だけ発火する。
    """
    activated: list[bool] = []
    seen_required: list[frozenset[str]] = []

    def verifier(required: frozenset[str]) -> bool:
        seen_required.append(required)
        return True

    controller = GlobalHotkeyController(
        lambda: activated.append(True),
        required_modifiers=frozenset({"cmd", "alt"}),
        modifier_state_verifier=verifier,
    )

    controller._on_press(StubKey("cmd"))
    controller._on_press(StubKey("alt"))

    assert activated == [True]
    assert seen_required == [frozenset({"cmd", "alt"})]


def test_global_hotkey_enter_fallback_activates_once_until_release() -> None:
    """
    Flet に Enter が届かない場合の保険は、キーリピートではなく 1 押下 1 回だけ発火する。
    """
    activated: list[bool] = []
    controller = GlobalHotkeyController(
        lambda: None,
        on_enter=lambda: activated.append(True),
        enter_enabled=lambda: True,
    )

    controller._on_press(StubKey("enter"))
    controller._on_press(StubKey("enter"))
    controller._on_release(StubKey("enter"))
    controller._on_press(StubKey("return"))

    assert activated == [True, True]


def test_global_hotkey_enter_fallback_respects_enabled_flag() -> None:
    """
    ランチャー非表示時など、許可されていない状態では Enter フォールバックを発火しない。
    """
    activated: list[bool] = []
    controller = GlobalHotkeyController(
        lambda: None,
        on_enter=lambda: activated.append(True),
        enter_enabled=lambda: False,
    )

    controller._on_press(StubKey("enter"))

    assert activated == []


def test_global_hotkey_enter_fallback_ignores_modified_enter(monkeypatch: Any) -> None:
    """
    Ctrl+Enter などの修飾キー付き Enter は Flet 側の通常ショートカットに任せる。
    """
    activated: list[bool] = []
    controller = GlobalHotkeyController(
        lambda: None,
        on_enter=lambda: activated.append(True),
        enter_enabled=lambda: True,
    )
    monkeypatch.setattr("launcher_app.services.hotkeys.platform.system", lambda: "Linux")

    controller._on_press(StubKey("ctrl"))
    controller._on_press(StubKey("enter"))

    assert activated == []
