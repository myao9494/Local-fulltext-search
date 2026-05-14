"""
グローバルホットキー定義が OS ごとの仕様に合うことを検証する。
"""

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
    Windows では Ctrl + Windows を表示名として返す。
    """
    assert hotkey_spec_for_platform("Windows") == "Ctrl + Windows"
    assert modifier_names_for_platform("Windows") == frozenset({"ctrl", "cmd"})


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
    Windows キーの release を取りこぼしても、次の Ctrl 単独押下で再発火しない。
    """
    state = ModifierChordState(frozenset({"ctrl", "cmd"}))

    assert state.press("cmd") is False
    assert state.press("ctrl") is True

    state.release("ctrl")
    assert state.press("ctrl") is False


def test_modifier_chord_ignores_stale_windows_key_before_activation() -> None:
    """
    Windows キーの押下状態だけが古く残っても、後から Ctrl 単独で発火しない。
    """
    now = 100.0
    state = ModifierChordState(frozenset({"ctrl", "cmd"}), now=lambda: now, max_chord_seconds=1.0)

    assert state.press("cmd") is False
    now = 102.0

    assert state.press("ctrl") is False


def test_global_hotkey_does_not_activate_when_required_modifiers_are_not_physically_down() -> None:
    """
    イベント履歴上は Ctrl+Win が揃っても、実キー状態が揃わなければ発火しない。
    """
    activated: list[bool] = []
    controller = GlobalHotkeyController(
        lambda: activated.append(True),
        required_modifiers=frozenset({"ctrl", "cmd"}),
        modifier_state_verifier=lambda required: False,
    )

    controller._on_press(StubKey("cmd"))
    controller._on_press(StubKey("ctrl"))

    assert activated == []


def test_global_hotkey_activates_when_required_modifiers_are_physically_down() -> None:
    """
    Ctrl+Win のイベントと実キー状態がどちらも揃った場合だけ発火する。
    """
    activated: list[bool] = []
    seen_required: list[frozenset[str]] = []

    def verifier(required: frozenset[str]) -> bool:
        seen_required.append(required)
        return True

    controller = GlobalHotkeyController(
        lambda: activated.append(True),
        required_modifiers=frozenset({"ctrl", "cmd"}),
        modifier_state_verifier=verifier,
    )

    controller._on_press(StubKey("cmd"))
    controller._on_press(StubKey("ctrl"))

    assert activated == [True]
    assert seen_required == [frozenset({"ctrl", "cmd"})]
