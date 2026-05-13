"""
グローバルホットキー定義が OS ごとの仕様に合うことを検証する。
"""

from launcher_app.services.hotkeys import ModifierChordState, hotkey_spec_for_platform, modifier_names_for_platform


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
