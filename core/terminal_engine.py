"""
Project-X-Nano Secure Terminal Engine
Isolated process execution with working directory persistence and execution limits.
"""

import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

IS_WIN = platform.system() == "Windows"


class TerminalEngine:
    """Safely executes administrative terminal commands."""

    def __init__(self, initial_cwd: Optional[str] = None, timeout: int = 60) -> None:
        self.cwd = str(initial_cwd or Path.home())
        self.timeout = timeout

    def run_command(self, cmd_text: str, shell: str = "cmd") -> Tuple[str, int, str]:
        """
        Execute command and return (output, return_code, updated_cwd).
        Interprets 'cd' internally to maintain persistent session state.
        """
        cmd = str(cmd_text).strip()[:2000]
        if not cmd:
            return "Empty command", 400, self.cwd

        # 1. Custom 'cd' directory handling
        cd_match = re.match(r'^cd(?:\s+/d)?\s+"?([^"]+?)"?$', cmd, re.IGNORECASE)
        if cd_match:
            target = cd_match.group(1).strip()
            target_path = (Path(self.cwd) / target).expanduser().resolve()
            if target_path.is_dir():
                self.cwd = str(target_path)
                return "", 0, self.cwd
            return "The system cannot find the path specified.", 1, self.cwd

        # 2. Build argument vector
        if IS_WIN:
            if shell == "powershell":
                argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
            else:
                argv = ["cmd", "/c", cmd]
            flags = 0x08000000  # CREATE_NO_WINDOW
        else:
            argv = ["bash", "-c", cmd]
            flags = 0

        # 3. Execute with timeout
        try:
            res = subprocess.run(
                argv,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,
                creationflags=flags
            )
            out = (res.stdout or "") + (res.stderr or "")
            code = res.returncode
        except subprocess.TimeoutExpired:
            out = f"(Command timed out after {self.timeout}s: interactive programs are not supported)"
            code = -1
        except Exception as e:
            out = f"Execution error: {e}"
            code = -1

        # Cap output to 30,000 chars to avoid memory exhaustion
        return out[-30000:], code, self.cwd
