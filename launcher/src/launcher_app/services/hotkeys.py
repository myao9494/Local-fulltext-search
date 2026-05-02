"""
ランチャー表示を切り替えるグローバルホットキー監視を提供する。
"""

from collections.abc import Callable
import platform
from typing import Any


def hotkey_spec_for_platform(system_name: str | None = None) -> str:
    """
    OS ごとの仕様に合う表示用ホットキー名を返す。
    """
    name = system_name or platform.system()
    if name == "Windows":
        return "Alt + Win"
    return "Option + Command"


def modifier_names_for_platform(system_name: str | None = None) -> frozenset[str]:
    """
    ランチャー表示トグルに使う修飾キー名を OS ごとに返す。

    NOTE: 現状 Mac/Win とも pynput の正規化名 {"cmd", "alt"} で統一。
    将来 Windows で Win キーを別名にする場合はここを分離する。
    """
    name = system_name or platform.system()
    if name == "Windows":
        return frozenset({"alt", "cmd"})
    return frozenset({"cmd", "alt"})


class ModifierChordState:
    """
    修飾キーだけのショートカットを安定して検出するため、押下状態と発火済み状態を管理する。
    """

    def __init__(self, required_modifiers: frozenset[str]) -> None:
        self.required_modifiers = required_modifiers
        self.pressed_modifiers: set[str] = set()
        self.activated = False

    def press(self, modifier_name: str | None) -> bool:
        """
        修飾キー押下を記録し、必要な組み合わせが揃った瞬間だけ True を返す。
        """
        if modifier_name is None:
            return False
        self.pressed_modifiers.add(modifier_name)
        if self.required_modifiers.issubset(self.pressed_modifiers) and not self.activated:
            self.activated = True
            return True
        return False

    def release(self, modifier_name: str | None) -> None:
        """
        修飾キー解除を記録し、組み合わせが崩れたら再発火可能にする。
        """
        if modifier_name is None:
            return
        self.pressed_modifiers.discard(modifier_name)
        if not self.required_modifiers.issubset(self.pressed_modifiers):
            self.activated = False


class GlobalHotkeyController:
    """
    pynput が利用できる環境でグローバルホットキー監視を開始・停止する。
    """

    def __init__(
        self,
        on_activate: Callable[[], None],
        *,
        hotkey: str | None = None,
        required_modifiers: frozenset[str] | None = None,
    ) -> None:
        self.on_activate = on_activate
        self.hotkey = hotkey or hotkey_spec_for_platform()
        self.state = ModifierChordState(required_modifiers or modifier_names_for_platform())
        self._listener: Any | None = None

    def start(self) -> bool:
        """
        pynput を遅延 import して監視を開始し、利用不可なら False を返す。
        """
        try:
            from pynput import keyboard
        except ImportError:
            return False
        self._listener = keyboard.Listener(
            on_press=lambda key: self._on_press(key),
            on_release=lambda key: self._on_release(key),
        )
        self._listener.start()
        return True

    def stop(self) -> None:
        """
        起動済みリスナーを停止する。
        """
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key: Any) -> None:
        """
        pynput のキー押下イベントを修飾キー名へ正規化して発火判定する。
        """
        if self.state.press(_modifier_name(key)):
            self.on_activate()

    def _on_release(self, key: Any) -> None:
        """
        pynput のキー解除イベントを修飾キー名へ正規化して状態を戻す。
        """
        self.state.release(_modifier_name(key))


def _modifier_name(key: Any) -> str | None:
    """
    pynput の Key / KeyCode を cmd・alt・ctrl・shift の短い名前へ変換する。
    """
    name = getattr(key, "name", None)
    if not isinstance(name, str):
        text = str(key)
        name = text.rsplit(".", maxsplit=1)[-1]
    normalized = name.lower()
    if normalized in {"cmd", "cmd_l", "cmd_r", "win", "win_l", "win_r"}:
        return "cmd"
    if normalized in {"alt", "alt_l", "alt_r", "option", "option_l", "option_r"}:
        return "alt"
    if normalized in {"ctrl", "ctrl_l", "ctrl_r", "control", "control_l", "control_r"}:
        return "ctrl"
    if normalized in {"shift", "shift_l", "shift_r"}:
        return "shift"
    return None
