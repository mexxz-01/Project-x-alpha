"""
Project-X-Nano Self-Healing File Integrity Engine
Automatically verifies and restores missing runtime dependencies, C modules,
icons, and Cloudflare binaries from the central GitHub repository.
"""

import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

# List of critical runtime dependencies (relative path -> remote url)
CRITICAL_FILES = [
    ("server.py", f"{GITHUB_RAW_BASE}/server.py"),
    ("tunnel.py", f"{GITHUB_RAW_BASE}/tunnel.py"),
    ("config.json", f"{GITHUB_RAW_BASE}/config.json"),
    ("favicon.png", f"{GITHUB_RAW_BASE}/favicon.png"),
    ("icon-192.png", f"{GITHUB_RAW_BASE}/icon-192.png"),
    ("icon.ico", f"{GITHUB_RAW_BASE}/icon.ico"),
    ("core/__init__.py", f"{GITHUB_RAW_BASE}/core/__init__.py"),
    ("core/native_bridge.py", f"{GITHUB_RAW_BASE}/core/native_bridge.py"),
    ("core/screen_engine.py", f"{GITHUB_RAW_BASE}/core/screen_engine.py"),
    ("core/input_engine.py", f"{GITHUB_RAW_BASE}/core/input_engine.py"),
    ("core/audio_engine.py", f"{GITHUB_RAW_BASE}/core/audio_engine.py"),
    ("core/terminal_engine.py", f"{GITHUB_RAW_BASE}/core/terminal_engine.py"),
    ("core/fleet_engine.py", f"{GITHUB_RAW_BASE}/core/fleet_engine.py"),
    ("native/remotepc_core.h", f"{GITHUB_RAW_BASE}/native/remotepc_core.h"),
    ("native/remotepc_core.c", f"{GITHUB_RAW_BASE}/native/remotepc_core.c"),
    ("native/build_native.bat", f"{GITHUB_RAW_BASE}/native/build_native.bat"),
    ("watchdog.ps1", f"{GITHUB_RAW_BASE}/watchdog.ps1"),
    ("watchdog.py", f"{GITHUB_RAW_BASE}/watchdog.py"),
    ("install_agent.bat", f"{GITHUB_RAW_BASE}/install_agent.bat"),
    ("uninstall.bat", f"{GITHUB_RAW_BASE}/uninstall.bat"),
]


class IntegrityEngine:
    """Monitors filesystem integrity and repairs missing files seamlessly."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def check_missing_files(self) -> List[Tuple[str, str]]:
        """Identify missing or empty critical files."""
        missing = []
        for rel_path, remote_url in CRITICAL_FILES:
            local_file = self.base_dir / rel_path
            if not local_file.exists() or local_file.stat().st_size == 0:
                missing.append((rel_path, remote_url))

        # Check Cloudflare binary
        cloudflared = self.base_dir / "cloudflared.exe"
        if not cloudflared.exists() or cloudflared.stat().st_size < 10000000:
            missing.append(("cloudflared.exe", CLOUDFLARED_URL))

        return missing

    def download_file(self, rel_path: str, remote_url: str) -> bool:
        """Download single file with retries."""
        dest = self.base_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(
                remote_url,
                headers={"User-Agent": "Project-X-Nano-Integrity/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if len(data) > 0:
                with open(dest, "wb") as f:
                    f.write(data)
                return True
        except Exception as e:
            print(f"[Integrity] Error downloading {rel_path}: {e}")
        return False

    def auto_repair(self) -> Dict[str, any]:
        """Scan and restore all missing components in parallel."""
        missing = self.check_missing_files()
        if not missing:
            return {"status": "ok", "missing_count": 0, "restored": []}

        restored = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(self.download_file, rel, url): rel for rel, url in missing}
            for fut in futures:
                rel = futures[fut]
                try:
                    if fut.result():
                        restored.append(rel)
                except Exception:
                    pass

        return {
            "status": "repaired" if len(restored) == len(missing) else "partial",
            "missing_count": len(missing),
            "restored_count": len(restored),
            "restored": restored,
        }
