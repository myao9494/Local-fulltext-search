"""
ランチャー表示を切り替えるグローバルホットキー監視を提供する。
"""

from collections.abc import Callable
import ctypes
import platform
import time
from typing import Any


def hotkey_spec_for_platform(system_name: str | None = None) -> str:
    """
    OS ごとの仕様に合う表示用ホットキー名を返す。
    """
    name = system_name or platform.system()
    if name == "Darwin":
        return "Command + Option"
    if name == "Windows":
        return "Ctrl + Windows"
    return "Ctrl + Shift"


def modifier_names_for_platform(system_name: str | None = None) -> frozenset[str]:
    """
    ランチャー表示トグルに使う修飾キー名を OS ごとに返す。

    macOS は Command + Option、Windows は Ctrl + Windows、その他 OS は Ctrl + Shift を使う。
    """
    name = system_name or platform.system()
    if name == "Darwin":
        return frozenset({"cmd", "alt"})
    if name == "Windows":
        return frozenset({"ctrl", "cmd"})
    return frozenset({"ctrl", "shift"})


class ModifierChordState:
    """
    修飾キーだけのショートカットを安定して検出するため、押下状態と発火済み状態を管理する。
    """

    def __init__(
        self,
        required_modifiers: frozenset[str],
        *,
        now: Callable[[], float] = time.monotonic,
        max_chord_seconds: float = 1.0,
    ) -> None:
        self.required_modifiers = required_modifiers
        self.pressed_modifiers: set[str] = set()
        self.pressed_at: dict[str, float] = {}
        self.activated = False
        self.now = now
        self.max_chord_seconds = max_chord_seconds

    def press(self, modifier_name: str | None) -> bool:
        """
        修飾キー押下を記録し、必要な組み合わせが揃った瞬間だけ True を返す。
        """
        if modifier_name is None:
            return False
        current_time = self.now()
        self._discard_stale_modifiers(current_time)
        self.pressed_modifiers.add(modifier_name)
        self.pressed_at[modifier_name] = current_time
        if self.required_modifiers.issubset(self.pressed_modifiers) and not self.activated:
            self.activated = True
            self.pressed_modifiers.clear()
            self.pressed_at.clear()
            return True
        return False

    def release(self, modifier_name: str | None) -> None:
        """
        修飾キー解除を記録し、組み合わせが崩れたら再発火可能にする。
        """
        if modifier_name is None:
            return
        self.pressed_modifiers.discard(modifier_name)
        self.pressed_at.pop(modifier_name, None)
        if not self.required_modifiers.issubset(self.pressed_modifiers):
            self.activated = False

    def reset(self) -> None:
        """
        OS 側の実キー状態と合わない場合に、推測した押下状態を破棄する。
        """
        self.pressed_modifiers.clear()
        self.pressed_at.clear()
        self.activated = False

    def _discard_stale_modifiers(self, current_time: float) -> None:
        """
        release を取りこぼした古い修飾キー状態を組み合わせ判定から外す。
        """
        stale_modifiers = [
            modifier
            for modifier, pressed_time in self.pressed_at.items()
            if current_time - pressed_time > self.max_chord_seconds
        ]
        for modifier in stale_modifiers:
            self.pressed_modifiers.discard(modifier)
            self.pressed_at.pop(modifier, None)
        if stale_modifiers and not self.required_modifiers.issubset(self.pressed_modifiers):
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
        modifier_state_verifier: Callable[[frozenset[str]], bool] | None = None,
        on_enter: Callable[[], None] | None = None,
        enter_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self.on_activate = on_activate
        self.hotkey = hotkey or hotkey_spec_for_platform()
        self.required_modifiers = required_modifiers or modifier_names_for_platform()
        self.state = ModifierChordState(self.required_modifiers)
        self.modifier_state_verifier = modifier_state_verifier or _required_modifiers_are_physically_down
        self.on_enter = on_enter
        self.enter_enabled = enter_enabled or (lambda: True)
        self._pressed_modifiers: set[str] = set()
        self._enter_pressed = False
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
        pynput のキー押下イベントを修飾キー名と Enter へ正規化して発火判定する。
        """
        modifier_name = _modifier_name(key)
        if modifier_name is not None:
            self._pressed_modifiers.add(modifier_name)
        if _is_enter_key(key):
            self._activate_enter_fallback()
            return
        if self.state.press(modifier_name):
            if not self.modifier_state_verifier(self.required_modifiers):
                self.state.reset()
                return
            self.on_activate()

    def _on_release(self, key: Any) -> None:
        """
        pynput のキー解除イベントを修飾キー名へ正規化して状態を戻す。
        """
        modifier_name = _modifier_name(key)
        if modifier_name is not None:
            self._pressed_modifiers.discard(modifier_name)
        if _is_enter_key(key):
            self._enter_pressed = False
            return
        self.state.release(modifier_name)

    def _activate_enter_fallback(self) -> None:
        """
        Flet に Enter が届かない場合の保険として、単独 Enter を 1 押下 1 回だけ通知する。
        """
        if self.on_enter is None or self._enter_pressed:
            return
        self._enter_pressed = True
        if not self.enter_enabled() or not _modifiers_are_clear(self._pressed_modifiers):
            return
        self.on_enter()


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


def _is_enter_key(key: Any) -> bool:
    """
    pynput の Enter / Return キー表現を判定する。
    """
    name = getattr(key, "name", None)
    if not isinstance(name, str):
        text = str(key)
        name = text.rsplit(".", maxsplit=1)[-1]
    normalized = name.lower().replace("-", "_").replace(" ", "_")
    return normalized in {"enter", "return", "numpad_enter", "numpadenter"}


def _modifiers_are_clear(pressed_modifiers: set[str]) -> bool:
    """
    Enter フォールバックが Ctrl+Enter 等を横取りしないよう修飾キー状態を確認する。
    """
    if platform.system() == "Windows":
        try:
            return not any(_windows_modifier_is_down(modifier) for modifier in {"ctrl", "cmd", "alt", "shift"})
        except Exception:
            return not pressed_modifiers
    return not pressed_modifiers


def _required_modifiers_are_physically_down(required_modifiers: frozenset[str]) -> bool:
    """
    Windows では発火直前に OS の実キー状態を確認し、Ctrl 単独の誤発火を防ぐ。
    """
    if platform.system() != "Windows":
        return True
    try:
        return all(_windows_modifier_is_down(modifier) for modifier in required_modifiers)
    except Exception:
        return False


def _windows_modifier_is_down(modifier_name: str) -> bool:
    """
    Win32 の GetAsyncKeyState で修飾キーが現在押されているか確認する。
    """
    key_codes = {
        "ctrl": (0x11, 0xA2, 0xA3),
        "cmd": (0x5B, 0x5C),
        "alt": (0x12, 0xA4, 0xA5),
        "shift": (0x10, 0xA0, 0xA1),
    }.get(modifier_name, ())
    user32 = ctypes.windll.user32
    return any(user32.GetAsyncKeyState(key_code) & 0x8000 for key_code in key_codes)
