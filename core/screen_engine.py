"""
Project-X-Nano High-Performance Screen Engine
Zero-copy GDI memory capture + hardware JPEG streaming pipeline (30-60 FPS).
"""

import io
import time
from typing import Generator, Optional, Tuple
import numpy as np

from .native_bridge import NativeBridge

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ScreenEngine:
    """Manages high-throughput screen captures and live MJPEG streaming."""

    def __init__(self, target_max_dim: int = 1280, default_quality: int = 60) -> None:
        self.bridge = NativeBridge()
        self.target_max_dim = target_max_dim
        self.default_quality = default_quality
        self._last_frame_bytes: Optional[bytes] = None
        self._last_frame_time: float = 0.0

    def capture_jpeg(self, quality: Optional[int] = None) -> Optional[bytes]:
        """
        Capture current desktop screen and return compressed JPEG bytes.
        Leverages direct Win32 C GDI buffer + OpenCV TurboJPEG encoder.
        """
        q = quality or self.default_quality
        raw_view, w, h = self.bridge.capture_screen_raw()

        if raw_view is None or w <= 0 or h <= 0:
            # Fallback for non-Windows or virtual desktops
            if HAS_PIL:
                from PIL import ImageGrab
                try:
                    img = ImageGrab.grab().convert("RGB")
                    img.thumbnail((self.target_max_dim, self.target_max_dim))
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=q)
                    return buf.getvalue()
                except Exception:
                    pass
            return None

        if HAS_CV2:
            # Zero-copy numpy wrapper over native C memory buffer
            arr = np.frombuffer(raw_view, dtype=np.uint8).reshape((h, w, 4))
            
            # Downscale if screen is larger than target_max_dim to save bandwidth
            if max(w, h) > self.target_max_dim:
                scale = self.target_max_dim / float(max(w, h))
                new_w, new_h = int(w * scale), int(h * scale)
                arr_resized = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
                # Convert BGRA to BGR
                bgr = cv2.cvtColor(arr_resized, cv2.COLOR_BGRA2BGR)
            else:
                bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

            encode_params = [
                cv2.IMWRITE_JPEG_QUALITY, q,
                cv2.IMWRITE_JPEG_OPTIMIZE, 0  # Speed over extreme compression
            ]
            ok, buf = cv2.imencode(".jpg", bgr, encode_params)
            if ok:
                return buf.tobytes()

        # Fallback using PIL from buffer
        if HAS_PIL:
            img = Image.frombuffer("RGBA", (w, h), raw_view, "raw", "BGRA", 0, 1).convert("RGB")
            if max(w, h) > self.target_max_dim:
                img.thumbnail((self.target_max_dim, self.target_max_dim))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=q)
            return buf.getvalue()

        return None

    def generate_mjpeg_stream(self, fps_limit: int = 30, quality: int = 55) -> Generator[bytes, None, None]:
        """
        Continuous multipart/x-mixed-replace MJPEG generator.
        Achieves smooth streaming with 1ms timer precision and rate limiting.
        """
        frame_interval = 1.0 / max(1, fps_limit)
        try:
            while True:
                start = time.perf_counter()
                jpeg = self.capture_jpeg(quality=quality)
                if jpeg:
                    self._last_frame_bytes = jpeg
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" +
                        jpeg + b"\r\n"
                    )

                elapsed = time.perf_counter() - start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except GeneratorExit:
            pass
        except Exception:
            pass
