"""
グローバルホットキー定義が OS ごとの仕様に合うことを検証する。
"""

from launcher_app.services.hotkeys import ModifierChordState, hotkey_spec_for_platform, modifier_names_for_platform


def test_hotkey_spec_for_macos() -> None:
    """
    macOS では Option + Command を表示名として返す。
    """
    assert hotkey_spec_for_platform("Darwin") == "Option + Command"
    assert modifier_names_for_platform("Darwin") == frozenset({"cmd", "alt"})


def test_hotkey_spec_for_windows() -> None:
    """
    Windows では Ctrl + Alt を表示名として返す。
    """
    assert hotkey_spec_for_platform("Windows") == "Ctrl + Alt"
    assert modifier_names_for_platform("Windows") == frozenset({"ctrl", "alt"})


def test_modifier_chord_activates_once_until_release() -> None:
    """
    修飾キーだけの組み合わせは揃った瞬間だけ発火し、解除後に再発火できる。
    """
    state = ModifierChordState(frozenset({"cmd", "alt"}))

    assert state.press("cmd") is False
    assert state.press("alt") is True
    assert state.press("alt") is False

    state.release("cmd")
    assert state.press("cmd") is True
