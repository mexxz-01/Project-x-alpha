"""
Project-X-Nano Fleet Engine
Parallel LAN discovery, node health probing, and multi-PC cluster orchestration.
"""

import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional


class FleetEngine:
    """Manages multi-machine discovery and fleet orchestration."""

    def __init__(self, port: int = 8765) -> None:
        self.port = port

    def probe_device(self, ip: str, port: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Quickly probe if a target IP runs RemotePC."""
        p = port or self.port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.35)
                if s.connect_ex((ip, p)) != 0:
                    return None

            req = urllib.request.Request(
                f"http://{ip}:{p}/api/stats",
                headers={"User-Agent": "RemotePC-Discovery"}
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return {
                        "ip": ip,
                        "port": p,
                        "host": data.get("host", ip),
                        "os": data.get("os", "Unknown"),
                        "cpu": data.get("cpu", 0),
                        "ram": data.get("ram", 0),
                        "url": f"http://{ip}:{p}"
                    }
        except Exception:
            pass
        return None

    def discover_local_subnet(self, my_ip: str) -> List[Dict[str, Any]]:
        """Scan /24 subnet for active RemotePC instances in parallel."""
        parts = my_ip.split(".")
        if len(parts) != 4:
            return []

        base = ".".join(parts[:3])
        ips = [f"{base}.{i}" for i in range(1, 255) if f"{base}.{i}" != my_ip]

        found = []
        with ThreadPoolExecutor(max_workers=50) as pool:
            results = pool.map(self.probe_device, ips)
            for r in results:
                if r:
                    found.append(r)
        return found

    def check_node_health(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Query real-time CPU/RAM status from a registered fleet node."""
        url = node.get("url", "").rstrip("/")
        info = dict(node)
        info["online"] = False
        info["cpu"] = 0
        info["ram"] = 0

        try:
            req = urllib.request.Request(
                f"{url}/api/stats",
                headers={"User-Agent": "RemotePC-FleetHealth"}
            )
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    info["online"] = True
                    info["cpu"] = data.get("cpu", 0)
                    info["ram"] = data.get("ram", 0)
                    if not info.get("name") or info["name"] == url:
                        info["name"] = data.get("host", url)
        except Exception:
            pass
        return info

    def broadcast_action(self, fleet: List[Dict[str, Any]], action: str, delay: int = 10) -> int:
        """Broadcast power/lock commands across all fleet PCs in parallel."""
        if action not in ("lock", "sleep", "restart", "shutdown"):
            return 0

        def _send(node: Dict[str, Any]) -> bool:
            url = node.get("url", "").rstrip("/")
            try:
                payload = json.dumps({"delay": delay}).encode("utf-8")
                req = urllib.request.Request(
                    f"{url}/api/power/{action}",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    return resp.status in (200, 204)
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=min(30, max(1, len(fleet)))) as pool:
            results = list(pool.map(_send, fleet))
        return sum(1 for ok in results if ok)
