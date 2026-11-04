import json
import time
import urllib.request
import threading
from pathlib import Path
from flask import request

_ASN_CACHE = {}
_ASN_LOCK = threading.Lock()

def get_asn_info(ip: str) -> str:
    """Fetch ASN or ISP description for public IP asynchronously or from memory cache."""
    if not ip or ip in ("127.0.0.1", "::1") or ip.startswith(("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")):
        return "LOCAL/LAN"
    
    with _ASN_LOCK:
        if ip in _ASN_CACHE:
            return _ASN_CACHE[ip]

    def _fetch():
        try:
            req = urllib.request.Request(f"https://ipapi.co/{ip}/org/", headers={"User-Agent": "Project-X-Audit/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                asn = resp.read().decode("utf-8").strip()
                if asn and "error" not in asn.lower():
                    with _ASN_LOCK:
                        _ASN_CACHE[ip] = asn
        except Exception:
            pass

    threading.Thread(target=_fetch, daemon=True).start()
    return _ASN_CACHE.get(ip, "ASN_PENDING")

def write_audit(log_file: Path, ip: str, action: str, details: dict = None):
    """Append structured JSON-lines audit record."""
    asn = get_asn_info(ip)
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": int(time.time()),
        "ip": ip,
        "asn": asn,
        "action": action,
    }
    if details:
        entry["details"] = details
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
