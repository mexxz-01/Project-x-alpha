"""
Project-X-Nano Native C/C++ Bridge
Provides high-performance native C hooks for Windows using direct Win32 C APIs
and optional compiled remotepc_core.dll.
"""

import ctypes
import os
import platform
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional, Tuple

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Predefined Virtual Key Codes
VK_MAP = {
    "mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
    "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play_pause": 0xB3,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
    "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "win": 0x5B, "f5": 0x74, "f11": 0x7A,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
    "c": 0x43, "v": 0x56, "x": 0x58, "a": 0x41, "z": 0x5A, "w": 0x57, "t": 0x54, "d": 0x44, "l": 0x4C,
}

if IS_WIN:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    # Mouse & Keyboard Constants
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004


class NativeBridge:
    """Singleton bridge providing direct C/C++ hardware hooks and fast GDI capture."""

    _instance: Optional["NativeBridge"] = None

    def __new__(cls) -> "NativeBridge":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_native()
        return cls._instance

    def _init_native(self) -> None:
        self.is_windows = IS_WIN
        self.dll = None
        self._screen_dc = None
        self._mem_dc = None
        self._hbitmap = None
        self._cached_w = 0
        self._cached_h = 0
        self._raw_buf = None

        if not self.is_windows:
            return

        # 1. Attempt loading compiled C DLL if available
        dll_paths = [
            Path(__file__).parent.parent / "remotepc_core.dll",
            Path(__file__).parent.parent / "native" / "remotepc_core.dll",
        ]
        for p in dll_paths:
            if p.exists():
                try:
                    self.dll = ctypes.CDLL(str(p))
                    if hasattr(self.dll, "RemotePC_Init"):
                        self.dll.RemotePC_Init()
                    break
                except Exception:
                    self.dll = None

        # 2. Configure DPI awareness so captures & inputs match actual physical pixels
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        # 3. Cache Win32 function pointers for maximum speed
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._kernel32 = ctypes.windll.kernel32

    def get_screen_size(self) -> Tuple[int, int]:
        """Return (width, height) of primary monitor."""
        if not self.is_windows:
            return 1920, 1080
        w = self._user32.GetSystemMetrics(0)
        h = self._user32.GetSystemMetrics(1)
        return max(1, w), max(1, h)

    def capture_screen_raw(self) -> Tuple[Optional[memoryview], int, int]:
        """
        Fast Win32 C GDI screen capture into zero-copy memoryview.
        Returns (memoryview_bgra, width, height) in ~1-3 milliseconds.
        """
        if not self.is_windows:
            return None, 0, 0

        w, h = self.get_screen_size()
        req_bytes = w * h * 4

        # Reuse DCs and Bitmap across frames to prevent memory allocation overhead
        if self._mem_dc is None or self._cached_w != w or self._cached_h != h:
            if self._hbitmap:
                self._gdi32.DeleteObject(self._hbitmap)
            if self._mem_dc:
                self._gdi32.DeleteDC(self._mem_dc)
            if self._screen_dc:
                self._user32.ReleaseDC(0, self._screen_dc)

            self._screen_dc = self._user32.GetDC(0)
            self._mem_dc = self._gdi32.CreateCompatibleDC(self._screen_dc)
            self._hbitmap = self._gdi32.CreateCompatibleBitmap(self._screen_dc, w, h)
            self._gdi32.SelectObject(self._mem_dc, self._hbitmap)
            self._cached_w = w
            self._cached_h = h
            self._raw_buf = (ctypes.c_char * req_bytes)()

        # Hardware BitBlt
        # SRCCOPY = 0x00CC0020, CAPTUREBLT = 0x40000000
        ok = self._gdi32.BitBlt(self._mem_dc, 0, 0, w, h, self._screen_dc, 0, 0, 0x00CC0020 | 0x40000000)
        if not ok:
            # Fallback to standard SRCCOPY
            self._gdi32.BitBlt(self._mem_dc, 0, 0, w, h, self._screen_dc, 0, 0, 0x00CC0020)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # Top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        res = self._gdi32.GetDIBits(self._mem_dc, self._hbitmap, 0, h, self._raw_buf, ctypes.byref(bmi), 0)
        if res == 0:
            return None, 0, 0

        return memoryview(self._raw_buf), w, h

    def mouse_move_relative(self, dx: int, dy: int) -> None:
        """Inject relative mouse movement."""
        if not self.is_windows:
            return
        dx = max(-500, min(500, int(dx)))
        dy = max(-500, min(500, int(dy)))
        self._user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)

    def mouse_click_absolute(self, fx: float, fy: float, right: bool = False, double: bool = False) -> None:
        """Click at normalized coordinates (0.0 to 1.0) with DPI scaling."""
        if not self.is_windows:
            return
        w, h = self.get_screen_size()
        tx = int(max(0.0, min(1.0, float(fx))) * (w - 1))
        ty = int(max(0.0, min(1.0, float(fy))) * (h - 1))

        self._user32.SetCursorPos(tx, ty)
        down = MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN
        up = MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP

        self._user32.mouse_event(down, 0, 0, 0, 0)
        self._user32.mouse_event(up, 0, 0, 0, 0)

        if double:
            self._user32.mouse_event(down, 0, 0, 0, 0)
            self._user32.mouse_event(up, 0, 0, 0, 0)

    def mouse_click_current(self, button: str = "left", double: bool = False) -> None:
        """Click at current mouse location."""
        if not self.is_windows:
            return
        if button == "right":
            down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            down, up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        else:
            down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

        self._user32.mouse_event(down, 0, 0, 0, 0)
        self._user32.mouse_event(up, 0, 0, 0, 0)
        if double:
            self._user32.mouse_event(down, 0, 0, 0, 0)
            self._user32.mouse_event(up, 0, 0, 0, 0)

    def mouse_scroll(self, amount: int) -> None:
        """Scroll mouse wheel."""
        if not self.is_windows:
            return
        delta = max(-50, min(50, int(amount))) * 120
        self._user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)

    def key_press(self, vk: int) -> None:
        """Tap a virtual key code."""
        if not self.is_windows:
            return
        self._user32.keybd_event(vk, 0, 0, 0)
        self._user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def key_combination(self, *vks: int) -> None:
        """Press and release a combination of keys (e.g. Ctrl+C)."""
        if not self.is_windows:
            return
        for vk in vks:
            self._user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            self._user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def type_unicode(self, text: str) -> None:
        """Type text using Unicode input events directly to active window."""
        if not self.is_windows:
            return
        for ch in text:
            code = ord(ch)
            self._user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            self._user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

    def get_memory_stats(self) -> Tuple[int, int, int]:
        """
        Query system RAM stats via native C GlobalMemoryStatusEx.
        Returns (total_mb, avail_mb, percent_used) in microseconds.
        """
        if not self.is_windows:
            return 16384, 8192, 50

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if self._kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_mb = int(mem.ullTotalPhys / (1024 * 1024))
            avail_mb = int(mem.ullAvailPhys / (1024 * 1024))
            return total_mb, avail_mb, int(mem.dwMemoryLoad)
        return 0, 0, 0

    def lock_workstation(self) -> bool:
        """Instantly lock PC screen."""
        if self.is_windows:
            return bool(self._user32.LockWorkStation())
        return False

    def suspend_pc(self, hibernate: bool = False) -> bool:
        """Put PC to sleep or hibernation via powrprof.dll."""
        if not self.is_windows:
            return False
        try:
            return bool(ctypes.windll.powrprof.SetSuspendState(int(hibernate), 0, 0))
        except Exception:
            return False
