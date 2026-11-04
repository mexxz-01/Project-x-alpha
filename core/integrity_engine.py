"""
Project-X-Nano Self-Healing File Integrity & Auto-Update Engine
Automatically verifies and restores missing runtime dependencies, C modules,
icons, and Cloudflare binaries from the central GitHub repository.
Also automatically checks and applies updates from GitHub when new commits are released.
"""

import os
import sys
import time
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import platform

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main"
GITHUB_API_COMMITS = "https://api.github.com/repos/mexxz-01/Project-x-alpha/commits/main"
EXE_URL = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"

IS_WIN = platform.system() == "Windows"
ARCH = platform.machine().lower()

if IS_WIN:
    CLOUDFLARED_BIN = "cloudflared.exe"
    CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
else:
    CLOUDFLARED_BIN = "cloudflared"
    if "aarch64" in ARCH or "arm64" in ARCH:
        CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    elif "arm" in ARCH:
        CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
    else:
        CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

# List of critical runtime dependencies (relative path -> remote url)
CRITICAL_FILES = [
    ("server.py", f"{GITHUB_RAW_BASE}/server.py"),
    ("tunnel.py", f"{GITHUB_RAW_BASE}/tunnel.py"),
    ("config.json", f"{GITHUB_RAW_BASE}/config.json"),
    ("version.json", f"{GITHUB_RAW_BASE}/version.json"),
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
    ("core/integrity_engine.py", f"{GITHUB_RAW_BASE}/core/integrity_engine.py"),
    ("native/remotepc_core.h", f"{GITHUB_RAW_BASE}/native/remotepc_core.h"),
    ("native/remotepc_core.c", f"{GITHUB_RAW_BASE}/native/remotepc_core.c"),
    ("native/build_native.bat", f"{GITHUB_RAW_BASE}/native/build_native.bat"),
    ("watchdog.ps1", f"{GITHUB_RAW_BASE}/watchdog.ps1"),
    ("watchdog.py", f"{GITHUB_RAW_BASE}/watchdog.py"),
    ("watchdog.sh", f"{GITHUB_RAW_BASE}/watchdog.sh"),
    ("install_agent.bat", f"{GITHUB_RAW_BASE}/install_agent.bat"),
    ("uninstall.bat", f"{GITHUB_RAW_BASE}/uninstall.bat"),
    ("uninstall.sh", f"{GITHUB_RAW_BASE}/uninstall.sh"),
    ("setup.ps1", f"{GITHUB_RAW_BASE}/setup.ps1"),
    ("setup.sh", f"{GITHUB_RAW_BASE}/setup.sh"),
]


class IntegrityEngine:
    """Monitors filesystem integrity, repairs missing files, and auto-updates from GitHub."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.commit_file = self.base_dir / ".last_commit"
        self.version_file = self.base_dir / "version.json"

    def check_missing_files(self) -> List[Tuple[str, str]]:
        """Identify missing or empty critical files."""
        missing = []
        for rel_path, remote_url in CRITICAL_FILES:
            local_file = self.base_dir / rel_path
            if not local_file.exists() or local_file.stat().st_size == 0:
                missing.append((rel_path, remote_url))

        # Check Cloudflare binary
        cloudflared = self.base_dir / CLOUDFLARED_BIN
        if not cloudflared.exists() or cloudflared.stat().st_size < 10000000:
            missing.append((CLOUDFLARED_BIN, CLOUDFLARED_URL))

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
                if not IS_WIN and (dest.suffix == ".sh" or dest.name == "cloudflared"):
                    try:
                        os.chmod(dest, 0o755)
                    except Exception:
                        pass
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

    def get_latest_github_commit(self) -> str:
        """Fetch the latest commit SHA from GitHub repository."""
        try:
            req = urllib.request.Request(
                GITHUB_API_COMMITS,
                headers={"User-Agent": "Project-X-Nano-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("sha", "")
        except Exception:
            return ""

    def get_current_commit(self) -> str:
        """Read currently recorded local commit SHA."""
        if self.commit_file.exists():
            try:
                return self.commit_file.read_text().strip()
            except Exception:
                pass
        return ""

    def check_for_updates(self) -> Dict[str, any]:
        """Check if an update is available on GitHub."""
        latest_sha = self.get_latest_github_commit()
        current_sha = self.get_current_commit()

        # Check version.json as fallback
        remote_version_info = {}
        try:
            req = urllib.request.Request(
                f"{GITHUB_RAW_BASE}/version.json",
                headers={"User-Agent": "Project-X-Nano-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                remote_version_info = json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass

        local_version_info = {}
        if self.version_file.exists():
            try:
                local_version_info = json.loads(self.version_file.read_text())
            except Exception:
                pass

        has_update = False
        if latest_sha and current_sha and latest_sha != current_sha:
            has_update = True
        elif remote_version_info.get("version") and local_version_info.get("version"):
            if remote_version_info.get("version") != local_version_info.get("version"):
                has_update = True

        return {
            "has_update": has_update,
            "current_sha": current_sha[:7] if current_sha else "unknown",
            "latest_sha": latest_sha[:7] if latest_sha else "unknown",
            "local_version": local_version_info.get("version", "1.0.0"),
            "remote_version": remote_version_info.get("version", local_version_info.get("version", "1.0.0")),
        }

    def apply_update(self) -> Dict[str, any]:
        """Download latest versions of all project files from GitHub."""
        print("[Updater] Starting automatic update from GitHub...")
        latest_sha = self.get_latest_github_commit()

        updated_files = []
        files_to_update = [f for f in CRITICAL_FILES if f[0] != "config.json"]
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(self.download_file, rel, url): rel for rel, url in files_to_update}
            for fut in futures:
                rel = futures[fut]
                try:
                    if fut.result():
                        updated_files.append(rel)
                except Exception:
                    pass

        # Also download latest compiled executable if frozen or present
        exe_path = self.base_dir / "Project-X-Nano.exe"
        if exe_path.exists() or (self.base_dir / "dist" / "Project-X-Nano.exe").exists():
            dest_exe = exe_path if exe_path.exists() else (self.base_dir / "dist" / "Project-X-Nano.exe")
            # Save as new binary to avoid locked file errors
            try:
                req = urllib.request.Request(EXE_URL, headers={"User-Agent": "Project-X-Nano-Updater/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    exe_data = resp.read()
                if len(exe_data) > 1000000:
                    with open(str(dest_exe) + ".new", "wb") as f:
                        f.write(exe_data)
                    updated_files.append("Project-X-Nano.exe.new")
            except Exception as e:
                print(f"[Updater] Could not fetch new EXE: {e}")

        if latest_sha:
            try:
                self.commit_file.write_text(latest_sha)
            except Exception:
                pass

        print(f"[Updater] Update complete: {len(updated_files)} files refreshed.")
        return {
            "status": "updated",
            "updated_count": len(updated_files),
            "updated_files": updated_files,
            "latest_sha": latest_sha[:7] if latest_sha else "",
        }
