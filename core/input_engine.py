"""
Project-X-Nano Input Engine
Low-latency virtual mouse and keyboard controller backed by Win32 C hooks.
"""

from typing import List, Optional
from .native_bridge import NativeBridge, VK_MAP

# Extended Hotkey Definitions
ALLOWED_KEYS = {
    "enter", "esc", "tab", "backspace", "delete", "space", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "win", "f5", "f11",
}

ALLOWED_HOTKEYS = {
    "alt+tab", "alt+f4", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+w", "ctrl+t",
    "win+d", "win+l", "ctrl+shift+esc", "ctrl+tab",
}


class InputEngine:
    """Dispatches virtual user inputs with zero latency."""

    def __init__(self) -> None:
        self.bridge = NativeBridge()

    def move_mouse_relative(self, dx: int, dy: int) -> bool:
        """Move cursor relative to current position."""
        self.bridge.mouse_move_relative(dx, dy)
        return True

    def click_mouse(self, button: str = "left", double: bool = False) -> bool:
        """Click at current cursor location."""
        if button not in ("left", "right", "middle"):
            return False
        self.bridge.mouse_click_current(button=button, double=double)
        return True

    def click_absolute(self, x_norm: float, y_norm: float, right: bool = False, double: bool = False) -> bool:
        """Direct tap-to-click on live screen stream with DPI compensation."""
        self.bridge.mouse_click_absolute(x_norm, y_norm, right=right, double=double)
        return True

    def scroll_mouse(self, amount: int) -> bool:
        """Scroll mouse wheel."""
        self.bridge.mouse_scroll(amount)
        return True

    def type_text(self, text: str, enter: bool = False) -> bool:
        """Type arbitrary Unicode text into active window."""
        safe_text = str(text)[:2000]
        self.bridge.type_unicode(safe_text)
        if enter:
            self.press_key("enter")
        return True

    def press_key(self, key_name: str) -> bool:
        """Press a single key."""
        key = key_name.lower().strip()
        vk = VK_MAP.get(key)
        if vk:
            self.bridge.key_press(vk)
            return True
        return False

    def trigger_hotkey(self, hotkey: str) -> bool:
        """Trigger multi-key combination (e.g. 'ctrl+c', 'alt+tab')."""
        combo = hotkey.lower().strip()
        parts = combo.split("+")
        vks = [VK_MAP.get(p.strip()) for p in parts]
        if None in vks:
            return False
        self.bridge.key_combination(*vks)
        return True
