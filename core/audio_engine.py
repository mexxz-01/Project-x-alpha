"""
Project-X-Nano Audio & Display Engine
High-efficiency Windows CoreAudio volume controls, monitor brightness, and speech.
"""

import os
import platform
import subprocess
import threading
from typing import Optional

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


class AudioEngine:
    """Manages master audio volume, display brightness, and TTS synthesizers."""

    def __init__(self) -> None:
        self._volume_endpoint = None
        self._com_initialized = False

    def _get_win_volume_endpoint(self):
        """Cache Windows CoreAudio IAudioEndpointVolume interface."""
        if not IS_WIN:
            return None
        if self._volume_endpoint is not None:
            return self._volume_endpoint

        try:
            import comtypes
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            import ctypes

            if not self._com_initialized:
                comtypes.CoInitialize()
                self._com_initialized = True

            dev = AudioUtilities.GetSpeakers()
            if hasattr(dev, "EndpointVolume"):
                self._volume_endpoint = dev.EndpointVolume
            else:
                iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._volume_endpoint = ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))
            return self._volume_endpoint
        except Exception:
            return None

    def get_volume(self) -> Optional[int]:
        """Get current master audio level (0-100)."""
        if IS_WIN:
            endpoint = self._get_win_volume_endpoint()
            if endpoint:
                try:
                    return int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
                except Exception:
                    # Invalidate cache if COM context expired
                    self._volume_endpoint = None
        return None

    def set_volume(self, level: int) -> bool:
        """Set master audio level (0-100)."""
        level = max(0, min(100, int(level)))
        if IS_WIN:
            endpoint = self._get_win_volume_endpoint()
            if endpoint:
                try:
                    endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
                    return True
                except Exception:
                    self._volume_endpoint = None
                    return False
        elif IS_MAC:
            subprocess.Popen(["osascript", "-e", f"set volume output volume {level}"])
            return True
        else:
            subprocess.Popen(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
            return True
        return False

    def get_brightness(self) -> Optional[int]:
        """Get monitor brightness (0-100)."""
        try:
            import screen_brightness_control as sbc
            levels = sbc.get_brightness()
            if levels:
                return int(levels[0])
        except Exception:
            pass
        return None

    def set_brightness(self, level: int) -> bool:
        """Set monitor brightness (0-100)."""
        level = max(0, min(100, int(level)))
        try:
            import screen_brightness_control as sbc
            sbc.set_brightness(level)
            return True
        except Exception:
            return False

    def play_sound(self, kind: str = "beep") -> None:
        """Play asynchronous alert sound on host PC."""
        def _worker():
            if IS_WIN:
                import winsound
                if kind == "alarm":
                    for _ in range(6):
                        winsound.Beep(1400, 250)
                        winsound.Beep(900, 250)
                else:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            elif IS_MAC:
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
            else:
                print("\a", end="")

        threading.Thread(target=_worker, daemon=True).start()

    def speak_text(self, text: str) -> None:
        """Synthesize spoken text on host PC."""
        clean = str(text)[:300].strip()
        if not clean:
            return

        def _worker():
            if IS_WIN:
                env = dict(os.environ, REMOTE_TTS_TEXT=clean)
                ps = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:REMOTE_TTS_TEXT)"
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    env=env,
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
            elif IS_MAC:
                subprocess.Popen(["say", clean])
            else:
                subprocess.Popen(["espeak", clean])

        threading.Thread(target=_worker, daemon=True).start()
