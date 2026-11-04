"""
Project-X-Nano - control your own PC from your phone/browser.
Run on the PC you want to control:   python server.py
Then open the printed URL on your phone (same Wi-Fi) and log in.
"""
import ctypes
import hmac
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import threading
import time
import ipaddress
import re
import urllib.request
import webbrowser
import stat
import shutil
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import Path
import psutil
from flask import Flask, Response, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash
try:
    from PIL import ImageGrab
except Exception:  # pillow optional
    ImageGrab = None
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
except Exception:  # no display / not installed
    pyautogui = None
from flask import send_file
from werkzeug.utils import secure_filename
try:
    import pyperclip
except Exception:
    pyperclip = None
import sys
import base64
import jwt
import pyotp
import qrcode
import crypto
import audit as audit_module
# High-performance Native C / C++ acceleration core
from core.native_bridge import NativeBridge
from core.screen_engine import ScreenEngine
from core.input_engine import InputEngine
from core.audio_engine import AudioEngine
from core.terminal_engine import TerminalEngine
from core.fleet_engine import FleetEngine
from core.integrity_engine import IntegrityEngine
# When built into an .exe, keep config.json next to the exe (not in a temp folder)
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
# Started hidden (pythonw / autostart)? Send output to a log file instead of nowhere.
if sys.stdout is None or sys.stderr is None:
    _log = open(BASE / "remotepc.log", "a", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
DEFAULT_CONFIG = {
    "port": 8765,
    "host": "0.0.0.0",  # use 127.0.0.1 to allow only this PC
    "password_hash": "scrypt:32768:8:1$EjrTHKvILpxhnGnv$7ef5a05c213ed971a60e2b27c9e19da0e8806bfd60629f39e468943005f1ea9c36c02c86e9d65a19b59b57927a9b763ef3b8f77d2dff37710050b722f4755091",
    "secret_key": "",
    "totp_secret": "",
    "totp_enabled": False,
    "registered_devices": [],
    "lan_opt_in": False,
    "ngrok_token": "2wCjLZ216UtiwlN4zYgnBP0u4MZ_3EYqNLgFc4xWCNg2vYPQ",
    # Folders the file browser may access. Empty = your home folder only.
    "file_roots": [],
    # Phone alerts even when the page is closed: pick a secret topic name, install the
    # free "ntfy" app on your phone and subscribe to the same topic. Empty = off.
    "ntfy_topic": "",
    "battery_low": 20,
    # Remote terminal (runs any command). Enabled by default (requires password re-entry).
    "terminal_enabled": True,
    "terminal_timeout": 60,
    # With "Start with PC": launch as Administrator at logon (needs the app started as admin once).
    "autostart_as_admin": False,
    # One-tap buttons. Only names listed here can be run (never free text from the web page).
    "commands": {
        "Network info": "ipconfig",
        "Flush DNS": "ipconfig /flushdns",
        "Disk space": "wmic logicaldisk get caption,freespace,size",
        "Clean temp files": "del /q /f /s %TEMP%\\*",
        "Backup Documents": "robocopy %USERPROFILE%\\Documents %USERPROFILE%\\Documents_Backup /E /XO /R:1 /W:1",
    },
    "apps": {
        "Notepad": "notepad.exe",
        "Calculator": "calc.exe",
        "File Explorer": "explorer.exe",
        "Task Manager": "taskmgr.exe",
        "Chrome": "start chrome",
    },
    # Multi-PC fleet registry (supports 50-100+ active PCs)
    "fleet": [],
    # Automatic tunnel port-forwarding
    "auto_forward": True,
    "tunnel_report_url": "",
}
# ---------------------------------------------------------------- config
def save_cfg():
    try:
        crypto.save_encrypted_config(CFG, CONFIG_FILE)
    except Exception as e:
        print(f"[Config] Save error: {e}")

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            loaded = crypto.load_encrypted_config(CONFIG_FILE)
            if loaded:
                cfg.update(loaded)
        except Exception:
            pass
    first_run_password = None
    if os.environ.get("PASSWORD"):
        cfg["password_hash"] = generate_password_hash(os.environ["PASSWORD"])
    if os.environ.get("SECRET_KEY"):
        cfg["secret_key"] = os.environ["SECRET_KEY"]
    if os.environ.get("NTFY_TOPIC"):
        cfg["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    if not cfg.get("password_hash"):
        cfg["password_hash"] = DEFAULT_CONFIG["password_hash"]
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
    try:
        crypto.save_encrypted_config(cfg, CONFIG_FILE)
    except Exception:
        pass
    return cfg, first_run_password
CFG, FIRST_PASSWORD = load_config()
app = Flask(__name__)
app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # stay logged in on your phone
)

def get_client_ip():
    """Extract real client IP safely, accounting for Cloudflare Tunnel or reverse proxies."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
# Initialize Native C / C++ acceleration engines
bridge = NativeBridge()
screen_engine = ScreenEngine()
input_engine = InputEngine()
audio_engine = AudioEngine()
fleet_engine = FleetEngine(port=CFG.get("port", 8765))
term_engine = TerminalEngine(timeout=int(CFG.get("terminal_timeout", 60)))
integrity_engine = IntegrityEngine(BASE)

# Background integrity check & self-healing worker
def _integrity_worker():
    time.sleep(6)
    try:
        res = integrity_engine.auto_repair()
        if res.get("missing_count", 0) > 0:
            print(f"[Integrity] Restored {res['restored_count']}/{res['missing_count']} missing files.")
    except Exception:
        pass

threading.Thread(target=_integrity_worker, daemon=True).start()

def background_auto_updater():
    time.sleep(15)
    while True:
        try:
            check = integrity_engine.check_for_updates()
            if check.get("has_update"):
                print(f"[AutoUpdater] New update found on GitHub ({check.get('latest_sha')}). Downloading...")
                res = integrity_engine.apply_update()
                print(f"[AutoUpdater] Update completed: {res.get('updated_count')} files refreshed.")
        except Exception as e:
            pass
        time.sleep(600)

threading.Thread(target=background_auto_updater, daemon=True).start()

# ---------------------------------------------------------------- auth & session management
FAILS = {}  # ip -> (count, locked_until)
DEVICE_LOCK = threading.Lock()
PENDING_TOTP_SECRETS = {}

def create_jwt_token(device_id: str, expires_in: int = 3600) -> str:
    payload = {
        "device_id": device_id,
        "exp": int(time.time()) + expires_in,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, CFG["secret_key"], algorithm="HS256")

def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, CFG["secret_key"], algorithms=["HS256"])
        device_id = payload.get("device_id")
        if not device_id:
            return None
        devices = CFG.get("registered_devices", [])
        for d in devices:
            if d.get("id") == device_id:
                if d.get("revoked", False):
                    return None
                d["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return payload
        return payload
    except Exception:
        return None

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            payload = verify_jwt_token(token)
            if payload:
                request.device_id = payload.get("device_id")
                return fn(*a, **kw)
        if session.get("ok"):
            device_id = session.get("device_id")
            if device_id:
                for d in CFG.get("registered_devices", []):
                    if d.get("id") == device_id and d.get("revoked", False):
                        session.clear()
                        return jsonify(error="Session revoked by administrator"), 401
            return fn(*a, **kw)
        return jsonify(error="Not logged in"), 401
    return wrapper

@app.get("/api/auth/state")
def api_auth_state():
    return jsonify(
        ok=True,
        totp_enabled=bool(CFG.get("totp_enabled") and CFG.get("totp_secret")),
        hostname=socket.gethostname()
    )

@app.post("/login")
@app.post("/api/login")
def login():
    ip = get_client_ip()
    count, locked = FAILS.get(ip, (0, 0))
    if time.time() < locked:
        remaining = int(locked - time.time())
        audit("Login rejected: rate-limit lockout active", {"ip": ip, "remaining_seconds": remaining})
        return jsonify(error=f"Too many attempts. Locked out for {remaining}s."), 429

    data = request.get_json(silent=True) or {}
    pw = data.get("password", "")
    totp_code = str(data.get("totp_code", "")).strip()
    remember = bool(data.get("remember", True))
    device_name = str(data.get("device_name", "Remote Client")).strip() or "Remote Client"
    device_id = str(data.get("device_id", "")).strip() or secrets.token_hex(8)

    if not pw or not check_password_hash(CFG["password_hash"], pw):
        count += 1
        lockout = 0
        if count >= 6:
            lockout = time.time() + 600
        elif count >= 4:
            lockout = time.time() + 120
        elif count >= 3:
            lockout = time.time() + 30
        FAILS[ip] = (count, lockout)
        push_alert(f"{count} failed login attempt(s) from {ip}")
        audit("login FAILED: bad password", {"attempts": count})
        time.sleep(1)
        return jsonify(error="Wrong password"), 403

    if CFG.get("totp_enabled") and CFG.get("totp_secret"):
        if not totp_code:
            return jsonify(totp_required=True, msg="2FA TOTP code required to complete login")
        totp = pyotp.TOTP(CFG["totp_secret"])
        if not totp.verify(totp_code, valid_window=2):
            count += 1
            FAILS[ip] = (count, time.time() + 60 if count >= 3 else 0)
            audit("login FAILED: invalid TOTP 2FA code", {"ip": ip})
            return jsonify(error="Invalid 2FA authentication code"), 403

    FAILS.pop(ip, None)
    session["ok"] = True
    session["device_id"] = device_id
    session.permanent = bool(remember)

    with DEVICE_LOCK:
        devices = CFG.setdefault("registered_devices", [])
        existing = next((d for d in devices if d.get("id") == device_id), None)
        if existing:
            existing["name"] = device_name
            existing["last_ip"] = ip
            existing["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
            existing["revoked"] = False
        else:
            devices.append({
                "id": device_id,
                "name": device_name,
                "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_active": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_ip": ip,
                "revoked": False,
            })
        save_cfg()

    expires_in = (30 * 86400) if remember else 86400
    token = create_jwt_token(device_id, expires_in=expires_in)
    push_alert(f"New authenticated login from {ip} ({device_name})")
    audit("login SUCCESS", {"device_id": device_id, "device_name": device_name, "remember": remember})
    return jsonify(ok=True, token=token, device_id=device_id)

@app.post("/logout")
@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

# ---------------------------------------------------------------- 2FA TOTP Endpoints
@app.get("/api/2fa/status")
@login_required
def api_2fa_status():
    return jsonify(enabled=bool(CFG.get("totp_enabled")), has_secret=bool(CFG.get("totp_secret")))

@app.post("/api/2fa/enroll")
@login_required
def api_2fa_enroll():
    ip = get_client_ip()
    device_id = getattr(request, "device_id", None) or session.get("device_id") or ip
    secret = pyotp.random_base32()
    PENDING_TOTP_SECRETS[device_id] = secret
    PENDING_TOTP_SECRETS[ip] = secret
    session["pending_totp_secret"] = secret
    hostname = socket.gethostname()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=f"Project-X-Nano ({hostname})", issuer_name="Project-X")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return jsonify(ok=True, secret=secret, qr_b64=qr_b64, otpauth=uri)

@app.post("/api/2fa/confirm")
@login_required
def api_2fa_confirm():
    ip = get_client_ip()
    device_id = getattr(request, "device_id", None) or session.get("device_id") or ip
    d = request.get_json(silent=True) or {}
    code = str(d.get("code", "")).strip()
    client_secret = str(d.get("secret", "")).strip()
    secret = client_secret or session.get("pending_totp_secret") or PENDING_TOTP_SECRETS.get(device_id) or PENDING_TOTP_SECRETS.get(ip) or CFG.get("totp_secret")
    if not secret:
        return jsonify(error="No 2FA setup in progress"), 400
    totp = pyotp.TOTP(secret)
    if totp.verify(code, valid_window=2):
        CFG["totp_secret"] = secret
        CFG["totp_enabled"] = True
        save_cfg()
        session.pop("pending_totp_secret", None)
        PENDING_TOTP_SECRETS.pop(device_id, None)
        PENDING_TOTP_SECRETS.pop(ip, None)
        audit("2FA TOTP activated successfully")
        return jsonify(ok=True, msg="Two-Factor Authentication (TOTP) successfully activated!")
    return jsonify(error="Invalid verification code. Please check your authenticator app and try again."), 400

@app.post("/api/2fa/disable")
@login_required
def api_2fa_disable():
    d = request.get_json(silent=True) or {}
    pw = d.get("password", "")
    if not pw or not check_password_hash(CFG["password_hash"], pw):
        return jsonify(error="Master password confirmation required"), 403
    CFG["totp_enabled"] = False
    CFG["totp_secret"] = ""
    save_cfg()
    audit("2FA TOTP disabled by user")
    return jsonify(ok=True, msg="Two-Factor Authentication disabled")

# ---------------------------------------------------------------- Device Session Revocation Endpoints
@app.get("/api/devices")
@login_required
def api_devices_list():
    return jsonify(ok=True, devices=CFG.get("registered_devices", []))

@app.post("/api/devices/revoke")
@login_required
def api_devices_revoke():
    d = request.get_json(silent=True) or {}
    target_id = str(d.get("device_id", "")).strip()
    if not target_id:
        return jsonify(error="Device ID required"), 400
    with DEVICE_LOCK:
        devices = CFG.get("registered_devices", [])
        for dev in devices:
            if dev.get("id") == target_id:
                dev["revoked"] = True
                save_cfg()
                audit("Device session revoked", {"revoked_device_id": target_id})
                return jsonify(ok=True, msg=f"Device {dev.get('name', target_id)} revoked successfully")
    return jsonify(error="Device not found"), 404

# ---------------------------------------------------------------- Audit Log Viewer Endpoint
@app.get("/api/audit/logs")
@login_required
def api_audit_logs():
    log_file = BASE / "audit.log"
    if not log_file.exists():
        return jsonify(ok=True, logs=[])
    try:
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        logs = []
        for line in lines[-200:]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{") and line.endswith("}"):
                try:
                    logs.append(json.loads(line))
                    continue
                except Exception:
                    pass
            logs.append({"timestamp": "", "action": line, "ip": "", "asn": ""})
        logs.reverse()
        return jsonify(ok=True, logs=logs)
    except Exception as e:
        return jsonify(error=str(e)), 500

# ---------------------------------------------------------------- Panic Wipe & Nuke Operations
def perform_nuke():
    print("[NUKE] Initiating PANIC WIPE sequence...")
    try:
        import tunnel
        tunnel.stop_tunnel()
    except Exception:
        pass

    if IS_WIN:
        for rname in ["Project-X-Nano", "RemotePC"]:
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rname}"], capture_output=True)

    try:
        (BASE / "uninstalling.lock").touch()
        if IS_WIN:
            subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%watchdog%'\" | Invoke-CimMethod -MethodName Terminate"], capture_output=True)
    except Exception:
        pass

    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_bytes(os.urandom(2048))
            CONFIG_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    try:
        (BASE / "public_url.txt").unlink(missing_ok=True)
        (BASE / "audit.log").write_text("", encoding="utf-8")
    except Exception:
        pass

    print("[NUKE] System credentials wiped, tunnel dropped, agent terminated.")

@app.post("/api/panic/nuke")
@login_required
def api_panic_nuke():
    d = request.get_json(silent=True) or {}
    pw = d.get("password", "")
    if not pw or not check_password_hash(CFG["password_hash"], pw):
        audit("PANIC NUKE rejected: bad password confirmation")
        return jsonify(error="Master password confirmation required to authorize emergency nuke"), 403
    audit("PANIC NUKE INITIATED from remote client")
    def _do_nuke():
        time.sleep(1.0)
        perform_nuke()
        os._exit(0)
    threading.Thread(target=_do_nuke, daemon=True).start()
    return jsonify(ok=True, msg="PANIC WIPE ENGAGED: Tunnels dropped, credentials wiped, agent terminating immediately.")
# ---------------------------------------------------------------- helpers
def run(cmd, shell=False):
    subprocess.Popen(cmd, shell=shell, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def press_key(vk):
    if IS_WIN:
        bridge.key_press(vk)
VK = {
    "mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
    "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play_pause": 0xB3,
}
def power(action, delay=5):
    delay = max(0, int(delay))
    if IS_WIN:
        if action == "lock":
            bridge.lock_workstation()
            return
        elif action == "sleep":
            bridge.suspend_pc(hibernate=False)
            return
        elif action == "hibernate":
            bridge.suspend_pc(hibernate=True)
            return
        table = {
            "shutdown": ["shutdown", "/s", "/t", str(delay)],
            "restart": ["shutdown", "/r", "/t", str(delay)],
            "logoff": ["shutdown", "/l"],
            "cancel": ["shutdown", "/a"],
        }
    elif IS_MAC:
        table = {
            "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
            "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
            "logoff": ["osascript", "-e", 'tell app "System Events" to log out'],
            "lock": ["pmset", "displaysleepnow"],
            "sleep": ["pmset", "sleepnow"],
        }
    else:
        table = {
            "shutdown": ["systemctl", "poweroff"],
            "restart": ["systemctl", "reboot"],
            "logoff": ["loginctl", "terminate-user", os.environ.get("USER", "")],
            "lock": ["loginctl", "lock-session"],
            "sleep": ["systemctl", "suspend"],
            "hibernate": ["systemctl", "hibernate"],
            "cancel": ["shutdown", "-c"],
        }
    if action not in table:
        raise ValueError("Not supported on this OS")
    run(table[action])
# ---------------------------------------------------------------- API
@app.post("/api/power/<action>")
@login_required
def api_power(action):
    delay = (request.get_json(silent=True) or {}).get("delay", 5)
    try:
        power(action, delay)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, msg=f"{action} sent")
@app.post("/api/security/lockdown")
@login_required
def api_emergency_lockdown():
    data = request.get_json(silent=True) or {}
    pw = data.get("password", "")
    if not (pw and check_password_hash(CFG["password_hash"], pw)):
        push_alert(f"Failed emergency lockdown attempt from {get_client_ip()}")
        audit("emergency lockdown FAILED: invalid password")
        return jsonify(error="Invalid master password confirmation"), 403
    audit(f"EMERGENCY LOCKDOWN executed from {request.remote_addr}")
    push_alert(f"🚨 EMERGENCY LOCKDOWN engaged from {request.remote_addr}")
    # 1. Terminate web browsers to clear in-memory sessions & protect accounts
    if IS_WIN:
        for browser in ["chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe"]:
            subprocess.run(["taskkill", "/F", "/IM", browser], capture_output=True)
    elif IS_MAC:
        for app in ["Google Chrome", "Safari", "Brave Browser", "Firefox"]:
            subprocess.run(["pkill", "-f", app], capture_output=True)
    # 2. Delayed lock and sign-out so HTTP response returns cleanly
    def do_lockdown():
        time.sleep(1.0)
        try:
            power("lock")
            time.sleep(0.5)
            power("logoff")
        except Exception:
            pass
    threading.Thread(target=do_lockdown, daemon=True).start()
    return jsonify(ok=True, msg="Emergency Lockdown engaged. Browser sessions terminated, PC locked and signed out.")
@app.post("/api/timer")
@login_required
def api_timer():
    """Schedule shutdown/restart after N minutes."""
    data = request.get_json(silent=True) or {}
    action = data.get("action", "shutdown")
    minutes = max(1, min(int(data.get("minutes", 30)), 24 * 60))
    if action not in ("shutdown", "restart"):
        return jsonify(error="bad action"), 400
    try:
        power(action, minutes * 60)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, msg=f"{action} in {minutes} min (use Cancel to stop)")
@app.post("/api/media/<key>")
@login_required
def api_media(key):
    if not IS_WIN or key not in VK:
        return jsonify(error="Media keys need Windows"), 400
    for _ in range(int((request.get_json(silent=True) or {}).get("times", 1))):
        press_key(VK[key])
    return jsonify(ok=True)
@app.post("/api/message")
@login_required
def api_message():
    text = str((request.get_json(silent=True) or {}).get("text", ""))[:500]
    if not text:
        return jsonify(error="empty"), 400
    if IS_WIN:
        threading.Thread(
            target=lambda: ctypes.windll.user32.MessageBoxW(0, text, "Message from remote", 0x40 | 0x40000),
            daemon=True,
        ).start()
    else:
        run(["notify-send", "Remote", text])
    return jsonify(ok=True)
@app.post("/api/open_url")
@login_required
def api_open_url():
    url = str((request.get_json(silent=True) or {}).get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return jsonify(ok=True)
@app.get("/api/apps")
@login_required
def api_apps():
    return jsonify(list(CFG["apps"].keys()))
@app.post("/api/launch")
@login_required
def api_launch():
    name = (request.get_json(silent=True) or {}).get("name")
    cmd = CFG["apps"].get(name)  # whitelist only: names from config.json
    if not cmd:
        return jsonify(error="Unknown app"), 400
    run(cmd, shell=True)
    return jsonify(ok=True)
@app.get("/api/stats")
@login_required
def api_stats():
    total_mb, avail_mb, ram_load = bridge.get_memory_stats()
    if ram_load == 0:
        vm = psutil.virtual_memory()
        ram_load = vm.percent
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    bat = psutil.sensors_battery()
    return jsonify(
        host=socket.gethostname(),
        os=f"{platform.system()} {platform.release()}",
        cpu=psutil.cpu_percent(interval=0.1),
        ram=ram_load,
        disk=disk.percent,
        battery=None if not bat else {"percent": round(bat.percent), "plugged": bat.power_plugged},
        uptime_min=int((time.time() - psutil.boot_time()) / 60),
    )
# ---------------------------------------------------------------- Coder & Power-User Diagnostics APIs

# 1. Network & Listening Ports Explorer
@app.get("/api/network/ports")
@login_required
def api_network_ports():
    ports = []
    seen = set()
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN or c.type == socket.SOCK_DGRAM:
                laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
                key = (laddr, c.pid)
                if key in seen:
                    continue
                seen.add(key)
                
                pname = "System"
                if c.pid:
                    try:
                        pname = psutil.Process(c.pid).name()
                    except Exception:
                        pname = f"PID {c.pid}"
                
                ports.append({
                    "port": c.laddr.port if c.laddr else 0,
                    "bind": c.laddr.ip if c.laddr else "0.0.0.0",
                    "proto": "TCP" if c.type == socket.SOCK_STREAM else "UDP",
                    "status": c.status or "LISTENING",
                    "pid": c.pid or 0,
                    "process": pname
                })
        ports.sort(key=lambda x: x["port"])
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(ok=True, ports=ports[:150], total=len(ports))

@app.post("/api/network/kill_port")
@login_required
def api_network_kill_port():
    d = request.get_json(silent=True) or {}
    pid = int(d.get("pid", 0))
    port = int(d.get("port", 0))
    if pid in (0, 4, os.getpid()):
        return jsonify(error="Protected system process cannot be terminated"), 400
    try:
        if pid:
            p = psutil.Process(pid)
            pname = p.name()
            p.kill()
            audit(f"Freed port {port} by terminating {pname} (PID {pid})")
            return jsonify(ok=True, msg=f"Freed port {port} (killed {pname})")
        return jsonify(error="No process associated with this port"), 400
    except Exception as e:
        if pid:
            if IS_WIN:
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            else:
                subprocess.run(f"kill -9 {pid}", shell=True, capture_output=True)
            return jsonify(ok=True, msg=f"Freed port {port} via force terminate")
        return jsonify(error=str(e)), 500

# 2. Windows & Linux Services Manager
@app.get("/api/services")
@login_required
def api_services_list():
    services = []
    try:
        if IS_WIN:
            cmd = 'powershell -NoProfile -Command "Get-Service | Select-Object -Property Name, DisplayName, Status, StartType | ConvertTo-Json -Compress"'
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            raw = json.loads(out)
            if isinstance(raw, dict):
                raw = [raw]
            for s in raw:
                services.append({
                    "name": s.get("Name", ""),
                    "display": s.get("DisplayName", ""),
                    "status": "Running" if s.get("Status") in (4, "Running") else "Stopped",
                    "startup": str(s.get("StartType", "Unknown"))
                })
        elif IS_LINUX:
            out = subprocess.check_output(
                ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 4:
                    s_unit = parts[0].replace(".service", "")
                    s_active = parts[2]
                    s_sub = parts[3]
                    s_desc = parts[4] if len(parts) > 4 else s_unit
                    services.append({
                        "name": s_unit,
                        "display": s_desc,
                        "status": "Running" if s_active == "active" and s_sub == "running" else "Stopped",
                        "startup": s_active
                    })
        services.sort(key=lambda x: (x["status"] != "Running", x["display"].lower()))
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(ok=True, services=services[:180], total=len(services))

@app.post("/api/services/action")
@login_required
def api_services_action():
    d = request.get_json(silent=True) or {}
    sname = d.get("name", "").strip()
    action = d.get("action", "").lower().strip()
    if not sname or action not in ("start", "stop", "restart"):
        return jsonify(error="Invalid service action"), 400
    if not re.match(r"^[a-zA-Z0-9_\-\.\ ]+$", sname):
        return jsonify(error="Invalid service name format"), 400
    try:
        if IS_WIN:
            cmd = ["powershell", "-NoProfile", "-Command", f"{action.capitalize()}-Service -Name '{sname}' {'-Force' if action != 'start' else ''}"]
            subprocess.run(cmd, capture_output=True)
        elif IS_LINUX:
            cmd = ["systemctl", action, sname]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode != 0:
                subprocess.run(["sudo", "systemctl", action, sname], capture_output=True)
        audit(f"Service {sname} action: {action}")
        return jsonify(ok=True, msg=f"Service '{sname}' {action} command issued")
    except Exception as e:
        return jsonify(error=str(e)), 500

# 3. Bi-Directional Clipboard Sync
@app.get("/api/clipboard")
@login_required
def api_clipboard_get():
    text = ""
    try:
        if pyperclip:
            text = pyperclip.paste()
        elif IS_WIN:
            text = subprocess.check_output("powershell -NoProfile -Command Get-Clipboard", shell=True, text=True, errors="replace").strip()
        elif IS_LINUX:
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"], ["wl-paste"]]:
                try:
                    text = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                    if text:
                        break
                except Exception:
                    pass
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(ok=True, text=text or "")

@app.post("/api/clipboard")
@login_required
def api_clipboard_set():
    d = request.get_json(silent=True) or {}
    text = d.get("text", "")
    try:
        if pyperclip:
            pyperclip.copy(text)
        elif IS_WIN:
            p = subprocess.Popen("clip", stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-8"))
        elif IS_LINUX:
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"], ["wl-copy"]]:
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(input=text.encode("utf-8"))
                    break
                except Exception:
                    pass
        audit("Clipboard updated remotely")
        return jsonify(ok=True, msg="Clipboard updated on PC")
    except Exception as e:
        return jsonify(error=str(e)), 500

# 4. Hardware Telemetry & CPU Cores
@app.get("/api/hardware/telemetry")
@login_required
def api_hardware_telemetry():
    try:
        cores = psutil.cpu_percent(percpu=True, interval=0.1)
        freq = psutil.cpu_freq()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        temps = {}
        try:
            if hasattr(psutil, "sensors_temperatures"):
                st = psutil.sensors_temperatures()
                for k, v in (st or {}).items():
                    if v:
                        temps[k] = round(v[0].current, 1)
        except Exception:
            pass

        return jsonify(
            ok=True,
            cores=cores,
            cpu_freq=round(freq.current, 1) if freq else 0,
            mem_total_gb=round(mem.total / (1024**3), 2),
            mem_used_gb=round(mem.used / (1024**3), 2),
            mem_pct=mem.percent,
            swap_pct=swap.percent,
            temperatures=temps
        )
    except Exception as e:
        return jsonify(error=str(e)), 500

# ---------------------------------------------------------------- Stealth Matrix Screen Lock
MATRIX_SCREEN_ACTIVE = False
_matrix_proc = None

@app.get("/matrix_screen")
def matrix_screen_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PROJECT X</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
  body, html {
    width: 100%; height: 100%;
    background-color: #000000;
    overflow: hidden;
    cursor: none;
    font-family: 'Consolas', 'Courier New', monospace;
  }
  canvas {
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    opacity: 0.35;
    z-index: 1;
  }
  .overlay {
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    z-index: 2;
    background: radial-gradient(circle, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.95) 85%);
  }
  .glitch-title {
    font-size: 56px;
    font-weight: 900;
    color: #00ff66;
    letter-spacing: 14px;
    text-shadow: 0 0 15px #00ff66, 0 0 35px rgba(0,255,102,0.6), 0 0 70px rgba(0,255,102,0.3);
    margin-bottom: 16px;
    animation: pulseGlow 2.5s infinite alternate;
  }
  .sub-banner {
    font-size: 15px;
    color: #00dd55;
    letter-spacing: 4px;
    opacity: 0.85;
    margin-bottom: 24px;
    text-shadow: 0 0 10px rgba(0,255,102,0.5);
  }
  .lock-box {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 20px;
    border: 1px solid rgba(0,255,102,0.4);
    background: rgba(0,20,5,0.7);
    border-radius: 6px;
    color: #00ff66;
    font-size: 13px;
    letter-spacing: 2px;
    box-shadow: 0 0 20px rgba(0,255,102,0.15);
  }
  .pulse-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #00ff66;
    box-shadow: 0 0 10px #00ff66;
    animation: blink 1.2s infinite;
  }
  @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
  @keyframes pulseGlow {
    0% { transform: scale(1); text-shadow: 0 0 15px #00ff66, 0 0 30px rgba(0,255,102,0.4); }
    100% { transform: scale(1.02); text-shadow: 0 0 25px #00ff66, 0 0 50px rgba(0,255,102,0.8); }
  }
  .footer-tag {
    position: fixed;
    bottom: 30px;
    font-size: 12px;
    color: rgba(0,255,102,0.4);
    letter-spacing: 3px;
  }
</style>
</head>
<body onclick="requestFullscreen()">
  <canvas id="matrix"></canvas>
  <div class="overlay">
    <div class="glitch-title">PROJECT X</div>
    <div class="sub-banner">TERMINAL ACCESS LOCKED · STEALTH PROTOCOL ACTIVE</div>
    <div class="lock-box">
      <span class="pulse-dot"></span>
      <span>SYSTEM LOCKED</span>
    </div>
    <div class="footer-tag">[ AUTHORIZED OVERRIDE REQUIRED ]</div>
  </div>

<script>
  function requestFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  }
  window.onload = requestFullscreen;

  // Matrix Digital Rain Animation
  const canvas = document.getElementById('matrix');
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const characters = '0123456789ABCDEFPROJECTXαβγδε$#@!*&';
  const fontSize = 16;
  const columns = Math.floor(canvas.width / fontSize);
  const drops = Array(columns).fill(1);

  function drawMatrix() {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#00ff66';
    ctx.font = fontSize + 'px monospace';

    for (let i = 0; i < drops.length; i++) {
      const char = characters.charAt(Math.floor(Math.random() * characters.length));
      ctx.fillText(char, i * fontSize, drops[i] * fontSize);
      if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
        drops[i] = 0;
      }
      drops[i]++;
    }
  }
  setInterval(drawMatrix, 35);
  window.addEventListener('resize', () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  });

  // Polling Server for Remote Dismissal
  setInterval(async () => {
    try {
      const res = await fetch('/api/matrix_screen/status');
      const data = await res.json();
      if (!data.active) {
        window.close();
        location.href = 'about:blank';
      }
    } catch(e) {}
  }, 1200);

  // Unclosable Trap + Host Keyboard Secret Unlock
  let buffer = '';
  window.addEventListener('keydown', (e) => {
    buffer += e.key.toLowerCase();
    if (buffer.length > 10) buffer = buffer.slice(-10);
    if (buffer.includes('mexxz')) {
      fetch('/api/matrix_screen/stop', { method: 'POST' });
      window.close();
      location.href = 'about:blank';
    }
    // Block standard navigation and window close keys
    if (['F11','F5','Escape','Tab',' '].includes(e.key) || (e.altKey && e.key === 'F4')) {
      e.preventDefault();
    }
  });
  window.addEventListener('contextmenu', e => e.preventDefault());
</script>
</body>
</html>"""

@app.get("/api/matrix_screen/status")
def api_matrix_screen_status():
    global MATRIX_SCREEN_ACTIVE
    return jsonify(active=MATRIX_SCREEN_ACTIVE)

@app.post("/api/matrix_screen/start")
@login_required
def api_matrix_screen_start():
    global MATRIX_SCREEN_ACTIVE, _matrix_proc
    MATRIX_SCREEN_ACTIVE = True
    port = CFG.get("port", 8765)
    url = f"http://127.0.0.1:{port}/matrix_screen"

    cmd = None
    if IS_WIN:
        edge_bin = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(edge_bin):
            cmd = [edge_bin, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run", "--edge-kiosk-type=fullscreen"]
        elif os.path.exists(chrome_bin):
            cmd = [chrome_bin, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run", "--noerrdialogs"]
        else:
            cmd = ["cmd.exe", "/c", f"start {url}"]
    elif IS_LINUX:
        for b in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"]:
            if shutil.which(b):
                cmd = [b, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run"]
                break
        if not cmd and shutil.which("firefox"):
            cmd = ["firefox", "--kiosk", url]
        if not cmd:
            cmd = ["xdg-open", url]

    if cmd:
        try:
            _matrix_proc = subprocess.Popen(cmd)
        except Exception as e:
            print(f"[MatrixScreen] Launch error: {e}")

    audit("Matrix Screen Lock activated on host PC")
    return jsonify(ok=True, msg="Matrix Screen Lock activated on PC")

@app.post("/api/matrix_screen/stop")
@login_required
def api_matrix_screen_stop():
    global MATRIX_SCREEN_ACTIVE, _matrix_proc
    MATRIX_SCREEN_ACTIVE = False
    if _matrix_proc:
        try:
            _matrix_proc.terminate()
            _matrix_proc.kill()
        except Exception:
            pass
        _matrix_proc = None

    if IS_WIN:
        subprocess.run('wmic process where "commandline like '%matrix_screen%'" call terminate', shell=True, capture_output=True)
    elif IS_LINUX:
        subprocess.run(["pkill", "-f", "matrix_screen"], capture_output=True)

    audit("Matrix Screen Lock dismissed")
    return jsonify(ok=True, msg="Matrix Screen Lock dismissed")

# ---------------------------------------------------------------- Fake Windows Update & Process Manager
FAKE_UPDATE_ACTIVE = False
_fake_update_proc = None

@app.get("/fake_update")
def fake_update_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Windows Update</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
  body, html {
    width: 100%; height: 100%;
    background-color: #000000;
    color: #ffffff;
    font-family: 'Segoe UI Light', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    overflow: hidden; cursor: none;
  }
  .spinner {
    position: relative;
    width: 68px; height: 68px;
    margin-bottom: 42px;
  }
  .spinner .dot {
    position: absolute;
    width: 68px; height: 68px;
    opacity: 0;
    transform: rotate(225deg);
    animation: orbit 5.5s infinite;
  }
  .spinner .dot:after {
    content: '';
    position: absolute;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #ffffff;
  }
  .spinner .dot:nth-child(2) { animation-delay: 240ms; }
  .spinner .dot:nth-child(3) { animation-delay: 480ms; }
  .spinner .dot:nth-child(4) { animation-delay: 720ms; }
  .spinner .dot:nth-child(5) { animation-delay: 960ms; }
  .spinner .dot:nth-child(6) { animation-delay: 1200ms; }

  @keyframes orbit {
    0% { transform: rotate(225deg); opacity: 1; animation-timing-function: ease-out; }
    7% { transform: rotate(345deg); animation-timing-function: linear; }
    30% { transform: rotate(455deg); animation-timing-function: ease-in-out; }
    39% { transform: rotate(690deg); animation-timing-function: linear; }
    70% { transform: rotate(815deg); opacity: 1; animation-timing-function: ease-out; }
    75% { transform: rotate(945deg); animation-timing-function: ease-out; }
    76% { transform: rotate(945deg); opacity: 0; }
    100% { transform: rotate(945deg); opacity: 0; }
  }

  .content { text-align: center; max-width: 650px; padding: 20px; }
  .title { font-size: 26px; font-weight: 300; margin-bottom: 12px; letter-spacing: 0.3px; }
  .pct { font-size: 22px; font-weight: 300; margin-bottom: 16px; opacity: 0.95; }
  .subtext { font-size: 16px; font-weight: 300; opacity: 0.8; line-height: 1.5; }
  .footer {
    position: fixed; bottom: 45px; left: 0; right: 0;
    text-align: center; font-size: 14px; opacity: 0.6;
    letter-spacing: 0.2px; font-weight: 300;
  }
</style>
</head>
<body onclick="requestFullscreen()">
  <div class="content">
    <div class="spinner">
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
    </div>
    <div class="title" id="stageTitle">Working on updates</div>
    <div class="pct"><span id="pctVal">14</span>% complete</div>
    <div class="subtext" id="stageDesc">Don't turn off your PC. This will take a while.</div>
  </div>
  <div class="footer">Your PC will restart several times</div>

<script>
  function requestFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  }
  window.onload = requestFullscreen;

  let p = 8;
  const pElem = document.getElementById('pctVal');
  const titleElem = document.getElementById('stageTitle');
  const descElem = document.getElementById('stageDesc');

  const titles = [
    { t: "Working on updates", d: "Don't turn off your PC. This will take a while." },
    { t: "Configuring updates for Windows", d: "Please keep your computer on and plugged in." },
    { t: "Working on updates", d: "Your device will restart automatically." }
  ];

  setInterval(() => {
    if (p < 99) {
      if (Math.random() > 0.35) {
        p += Math.floor(Math.random() * 2) + 1;
        pElem.textContent = p;
        if (p === 32 || p === 68 || p === 89) {
          const item = titles[Math.floor(Math.random() * titles.length)];
          titleElem.textContent = item.t;
          descElem.textContent = item.d;
        }
      }
    }
  }, 3200);

  setInterval(async () => {
    try {
      const res = await fetch('/api/fake_update/status');
      const data = await res.json();
      if (!data.active) {
        window.close();
        location.href = 'about:blank';
      }
    } catch(e) {}
  }, 1200);

  let buffer = '';
  window.addEventListener('keydown', (e) => {
    buffer += e.key.toLowerCase();
    if (buffer.length > 10) buffer = buffer.slice(-10);
    if (buffer.includes('mexxz')) {
      fetch('/api/fake_update/stop', { method: 'POST' });
      window.close();
      location.href = 'about:blank';
    }
    if (['F11','F5','Escape','Tab',' '].includes(e.key) || (e.altKey && e.key === 'F4')) {
      e.preventDefault();
    }
  });
  window.addEventListener('contextmenu', e => e.preventDefault());
</script>
</body>
</html>"""

@app.get("/api/fake_update/status")
def api_fake_update_status():
    global FAKE_UPDATE_ACTIVE
    return jsonify(active=FAKE_UPDATE_ACTIVE)

@app.post("/api/fake_update/start")
@login_required
def api_fake_update_start():
    global FAKE_UPDATE_ACTIVE, _fake_update_proc
    FAKE_UPDATE_ACTIVE = True
    port = CFG.get("port", 8765)
    url = f"http://127.0.0.1:{port}/fake_update"

    cmd = None
    if IS_WIN:
        edge_bin = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(edge_bin):
            cmd = [edge_bin, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run", "--edge-kiosk-type=fullscreen"]
        elif os.path.exists(chrome_bin):
            cmd = [chrome_bin, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run", "--noerrdialogs"]
        else:
            cmd = ["cmd.exe", "/c", f"start {url}"]
    elif IS_LINUX:
        for b in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"]:
            if shutil.which(b):
                cmd = [b, f"--app={url}", "--start-fullscreen", "--kiosk", "--no-first-run"]
                break
        if not cmd and shutil.which("firefox"):
            cmd = ["firefox", "--kiosk", url]
        if not cmd:
            cmd = ["xdg-open", url]

    if cmd:
        try:
            _fake_update_proc = subprocess.Popen(cmd)
        except Exception as e:
            print(f"[FakeUpdate] Launch error: {e}")

    audit("Fake Windows Update launched on host PC")
    return jsonify(ok=True, msg="Fake Windows Update screen activated on PC")

@app.post("/api/fake_update/stop")
@login_required
def api_fake_update_stop():
    global FAKE_UPDATE_ACTIVE, _fake_update_proc
    FAKE_UPDATE_ACTIVE = False
    if _fake_update_proc:
        try:
            _fake_update_proc.terminate()
            _fake_update_proc.kill()
        except Exception:
            pass
        _fake_update_proc = None

    if IS_WIN:
        subprocess.run('wmic process where "commandline like '%fake_update%'" call terminate', shell=True, capture_output=True)
    elif IS_LINUX:
        subprocess.run(["pkill", "-f", "fake_update"], capture_output=True)

    audit("Fake Windows Update dismissed")
    return jsonify(ok=True, msg="Fake Windows Update dismissed")

# Enhanced Live Process Management APIs
@app.get("/api/processes")
@login_required
def api_processes():
    procs = []
    for p in psutil.process_iter(["pid", "name", "status", "memory_info", "cpu_percent"]):
        try:
            info = p.info
            mem_mb = round((info["memory_info"].rss if info["memory_info"] else 0) / (1024 * 1024), 1)
            cpu = round(info["cpu_percent"] or 0.0, 1)
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "Unknown",
                "status": info["status"] or "running",
                "mem_mb": mem_mb,
                "cpu": cpu
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    sort_by = request.args.get("sort", "mem")
    if sort_by == "cpu":
        procs.sort(key=lambda x: x["cpu"], reverse=True)
    elif sort_by == "name":
        procs.sort(key=lambda x: x["name"].lower())
    else:
        procs.sort(key=lambda x: x["mem_mb"], reverse=True)

    return jsonify(ok=True, processes=procs[:150], total=len(procs))

@app.post("/api/processes/kill")
@login_required
def api_processes_kill():
    d = request.get_json(silent=True) or {}
    pid = int(d.get("pid", 0))
    if pid in (0, 4, os.getpid()):
        return jsonify(error="Protected system process cannot be terminated"), 400
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.kill()
        audit(f"Killed process {name} (PID {pid})")
        return jsonify(ok=True, msg=f"Killed {name} (PID {pid})")
    except psutil.NoSuchProcess:
        return jsonify(error="Process already stopped"), 404
    except psutil.AccessDenied:
        if IS_WIN:
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            return jsonify(ok=True, msg=f"Force terminated PID {pid} via taskkill")
        return jsonify(error="Access denied to terminate this process"), 403
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.post("/api/processes/suspend")
@login_required
def api_processes_suspend():
    d = request.get_json(silent=True) or {}
    pid = int(d.get("pid", 0))
    if pid in (0, 4, os.getpid()):
        return jsonify(error="Protected system process cannot be suspended"), 400
    try:
        p = psutil.Process(pid)
        p.suspend()
        audit(f"Suspended process {p.name()} (PID {pid})")
        return jsonify(ok=True, msg=f"Suspended {p.name()} (PID {pid})")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.post("/api/processes/resume")
@login_required
def api_processes_resume():
    d = request.get_json(silent=True) or {}
    pid = int(d.get("pid", 0))
    try:
        p = psutil.Process(pid)
        p.resume()
        audit(f"Resumed process {p.name()} (PID {pid})")
        return jsonify(ok=True, msg=f"Resumed {p.name()} (PID {pid})")
    except Exception as e:
        return jsonify(error=str(e)), 500
@app.get("/api/screenshot")
@login_required
def api_screenshot():
    jpeg = screen_engine.capture_jpeg(quality=60)
    if not jpeg:
        return jsonify(error="Screen capture failed"), 500
    return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
def generate_screen_stream():
    return screen_engine.generate_mjpeg_stream(fps_limit=30, quality=55)
@app.get("/api/stream/screen")
@login_required
def api_stream_screen():
    return Response(generate_screen_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")
# ---------------------------------------------------------------- mouse & keyboard
ALLOWED_KEYS = {
    "enter", "esc", "tab", "backspace", "delete", "space", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "win", "f5", "f11",
}
ALLOWED_HOTKEYS = {
    "alt+tab", "alt+f4", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+w", "ctrl+t",
    "win+d", "win+l", "ctrl+shift+esc", "ctrl+tab",
}
@app.post("/api/mouse/move")
@login_required
def api_mouse_move():
    d = request.get_json(silent=True) or {}
    dx, dy = int(d.get("dx", 0)), int(d.get("dy", 0))
    input_engine.move_mouse_relative(dx, dy)
    return jsonify(ok=True)
@app.post("/api/mouse/click")
@login_required
def api_mouse_click():
    d = request.get_json(silent=True) or {}
    button = d.get("button", "left")
    if button not in ("left", "right", "middle"):
        return jsonify(error="bad button"), 400
    input_engine.click_mouse(button=button, double=bool(d.get("double")))
    return jsonify(ok=True)
@app.post("/api/mouse/scroll")
@login_required
def api_mouse_scroll():
    amount = int((request.get_json(silent=True) or {}).get("amount", 0))
    input_engine.scroll_mouse(amount)
    return jsonify(ok=True)
@app.post("/api/keyboard/type")
@login_required
def api_type():
    d = request.get_json(silent=True) or {}
    text = str(d.get("text", ""))[:1000]
    input_engine.type_text(text, enter=bool(d.get("enter")))
    return jsonify(ok=True)
@app.post("/api/keyboard/key")
@login_required
def api_key():
    key = str((request.get_json(silent=True) or {}).get("key", "")).lower()
    if key in ALLOWED_KEYS:
        input_engine.press_key(key)
    elif key in ALLOWED_HOTKEYS:
        input_engine.trigger_hotkey(key)
    else:
        return jsonify(error="Key not allowed"), 400
    return jsonify(ok=True)
# ---------------------------------------------------------------- file browser
def file_roots():
    configured = CFG.get("file_roots", [])
    if configured:
        return [Path(r).expanduser().resolve() for r in configured]
    if IS_WIN:
        drives = []
        try:
            for p in psutil.disk_partitions(all=False):
                drives.append(Path(p.mountpoint).resolve())
        except Exception:
            pass
        if drives:
            return drives
    return [Path.home().resolve()]
def safe_path(p):
    """Resolve p and make sure it is inside an allowed root if file_roots is configured."""
    path = Path(p).expanduser().resolve()
    configured = CFG.get("file_roots", [])
    if configured:
        for root in [Path(r).expanduser().resolve() for r in configured]:
            if path == root or root in path.parents:
                return path
        raise PermissionError("Outside allowed folders")
    return path
@app.get("/api/drives")
@login_required
def api_drives():
    drives = []
    if IS_WIN:
        for p in psutil.disk_partitions(all=False):
            mount = p.mountpoint
            if not mount.endswith("\\"):
                mount += "\\"
            info = {"mount": mount, "device": p.device}
            try:
                u = psutil.disk_usage(mount)
                info["free_gb"] = round(u.free / (1024**3), 1)
                info["total_gb"] = round(u.total / (1024**3), 1)
            except Exception:
                pass
            drives.append(info)
    else:
        drives.append({"mount": "/", "device": "/"})
    return jsonify(drives=drives)
@app.get("/api/files")
@login_required
def api_files():
    raw = request.args.get("path") or ""
    try:
        path = safe_path(raw) if raw else file_roots()[0]
        if not path.is_dir():
            return jsonify(error="Not a folder"), 400
        items = []
        try:
            for e in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    st = e.stat()
                    items.append({"name": e.name, "dir": e.is_dir(), "size": st.st_size})
                except OSError:
                    continue
        except PermissionError:
            return jsonify(error="Access denied to this folder"), 403
        parent = str(path.parent) if path.parent != path else None
        return jsonify(path=str(path), parent=parent, items=items[:500])
    except PermissionError as e:
        return jsonify(error=str(e)), 403
@app.get("/api/files/download")
@login_required
def api_download():
    try:
        path = safe_path(request.args.get("path", ""))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    if not path.is_file():
        return jsonify(error="Not a file"), 400
    return send_file(path, as_attachment=True)
@app.get("/download/apk")
def download_apk():
    for name in ["Project-X-Nano.apk", "RemotePC-Controller.apk"]:
        for loc in [BASE / name, BASE / "dist" / name]:
            if loc.exists():
                return send_file(
                    loc,
                    as_attachment=True,
                    download_name="Project-X-Nano.apk",
                    mimetype="application/vnd.android.package-archive"
                )
    return jsonify(error="APK not found on server"), 404
@app.post("/api/files/upload")
@login_required
def api_upload():
    try:
        folder = safe_path(request.form.get("path", ""))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    saved = 0
    for f in request.files.getlist("files"):
        name = secure_filename(f.filename or "")
        if not name:
            continue
        target = folder / name
        n = 1
        while target.exists():  # never overwrite
            target = folder / f"{target.stem.split(' (')[0]} ({n}){Path(name).suffix}"
            n += 1
        f.save(target)
        saved += 1
    return jsonify(ok=True, msg=f"Uploaded {saved} file(s)")
@app.post("/api/files/open")
@login_required
def api_file_open():
    try:
        path = safe_path((request.get_json(silent=True) or {}).get("path", ""))
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    if IS_WIN:
        os.startfile(str(path))  # noqa
    elif IS_MAC:
        run(["open", str(path)])
    else:
        run(["xdg-open", str(path)])
    return jsonify(ok=True, msg="Opened on PC")

@app.post("/api/files/delete")
@login_required
def api_file_delete():
    d = request.get_json(silent=True) or {}
    raw_path = d.get("path", "")
    use_admin = bool(d.get("admin", False))
    if not raw_path:
        return jsonify(error="Path is required"), 400
    try:
        path = safe_path(raw_path)
    except PermissionError as e:
        return jsonify(error=str(e)), 403

    if not path.exists():
        return jsonify(error="File or folder does not exist"), 404

    # Critical system path protection: prevent deleting drive roots or OS core directories
    str_lower = str(path).lower().rstrip("\\/")
    if path == path.parent or str_lower in ("c:", "c:\\windows", "c:\\windows\\system32", "", "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/proc", "/sys", "/usr"):
        return jsonify(error="Protected system path cannot be deleted"), 403

    def make_writable(p):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass

    # Standard deletion attempt
    if not use_admin:
        try:
            if path.is_file() or path.is_symlink():
                make_writable(path)
                path.unlink()
            elif path.is_dir():
                def on_rm_error(func, p, exc_info):
                    make_writable(p)
                    try:
                        func(p)
                    except Exception:
                        pass
                shutil.rmtree(path, onerror=on_rm_error)
            audit(f"Deleted file/dir: {path}")
            return jsonify(ok=True, msg=f"Deleted: {path.name}")
        except PermissionError:
            use_admin = True
        except Exception as e:
            if not IS_WIN:
                return jsonify(error=str(e)), 500
            use_admin = True

    # Administrator authority force deletion on Windows
    if IS_WIN:
        try:
            str_path = str(path)
            subprocess.run(f'takeown /f "{str_path}" {"/r /d y" if path.is_dir() else ""}', shell=True, capture_output=True)
            subprocess.run(f'icacls "{str_path}" /grant administrators:F {"/t" if path.is_dir() else ""} /c /q', shell=True, capture_output=True)
            if path.is_dir():
                subprocess.run(f'rmdir /s /q "{str_path}"', shell=True, capture_output=True)
            else:
                subprocess.run(f'del /f /q /a "{str_path}"', shell=True, capture_output=True)

            if not path.exists():
                audit(f"Deleted with admin authority: {path}")
                return jsonify(ok=True, msg=f"Deleted with administrator privileges: {path.name}")
            else:
                arg_action = f'/c del /f /q /a """{str_path}"""' if path.is_file() else f'/c rmdir /s /q """{str_path}"""'
                elevate_cmd = ['powershell', '-NoProfile', '-Command', f"Start-Process cmd -ArgumentList '{arg_action}' -Verb RunAs -Wait"]
                subprocess.run(elevate_cmd, capture_output=True)
                if not path.exists():
                    audit(f"Deleted with elevated admin authority: {path}")
                    return jsonify(ok=True, msg=f"Deleted with elevated administrator privileges: {path.name}")
                return jsonify(error="Access denied: file is locked by system or running process"), 403
        except Exception as e:
            return jsonify(error=f"Admin deletion failed: {e}"), 500
    elif IS_LINUX and use_admin:
        try:
            subprocess.run(["sudo", "rm", "-rf", str(path)], capture_output=True)
            if not path.exists():
                audit(f"Deleted with root authority: {path}")
                return jsonify(ok=True, msg=f"Deleted with root administrator privileges: {path.name}")
        except Exception as e:
            return jsonify(error=f"Root delete failed: {e}"), 500

    return jsonify(error="Deletion failed"), 500

# ---------------------------------------------------------------- alerts / notifications
ALERTS = []
ALERT_LOCK = threading.Lock()
WATCHES = set()
def push_alert(text):
    with ALERT_LOCK:
        aid = (ALERTS[-1]["id"] + 1) if ALERTS else 1
        ALERTS.append({"id": aid, "time": time.strftime("%H:%M"), "text": text})
        del ALERTS[:-50]
    topic = CFG.get("ntfy_topic")
    if topic:
        def send():
            try:
                req = urllib.request.Request(
                    f"https://ntfy.sh/{topic}", data=text.encode("utf-8"), headers={"Title": "Remote PC"}
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
        threading.Thread(target=send, daemon=True).start()
def monitor():
    low_sent = False
    while True:
        try:
            bat = psutil.sensors_battery()
            if bat:
                low = int(CFG.get("battery_low", 20))
                if not bat.power_plugged and bat.percent <= low:
                    if not low_sent:
                        push_alert(f"Battery low: {round(bat.percent)}%")
                        low_sent = True
                elif bat.power_plugged or bat.percent > low + 5:
                    low_sent = False
            if WATCHES:
                running = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
                for name in list(WATCHES):
                    if name not in running:
                        WATCHES.discard(name)
                        push_alert(f"{name} has finished / closed")
        except Exception:
            pass
        time.sleep(15)
@app.get("/api/alerts")
@login_required
def api_alerts():
    since = int(request.args.get("since", 0))
    with ALERT_LOCK:
        new = [a for a in ALERTS if a["id"] > since]
        last = ALERTS[-1]["id"] if ALERTS else 0
        recent = ALERTS[-5:][::-1]
    return jsonify(alerts=new, last=last, recent=recent)
@app.post("/api/watch")
@login_required
def api_watch():
    name = str((request.get_json(silent=True) or {}).get("name", "")).lower()
    if not any((p.info["name"] or "").lower() == name for p in psutil.process_iter(["name"])):
        return jsonify(error="Process not running"), 400
    WATCHES.add(name)
    return jsonify(ok=True, msg=f"Will alert when {name} closes")
# (Unified bi-directional clipboard engine registered at line 495)
# ---------------------------------------------------------------- volume & brightness
@app.get("/api/volume")
@login_required
def api_volume_get():
    return jsonify(level=audio_engine.get_volume())
@app.post("/api/volume")
@login_required
def api_volume_set():
    level = max(0, min(100, int((request.get_json(silent=True) or {}).get("level", 0))))
    ok = audio_engine.set_volume(level)
    if not ok:
        return jsonify(error="Volume control unavailable"), 500
    return jsonify(ok=True)
@app.get("/api/brightness")
@login_required
def api_bri_get():
    return jsonify(level=audio_engine.get_brightness())
@app.post("/api/brightness")
@login_required
def api_bri_set():
    level = max(0, min(100, int((request.get_json(silent=True) or {}).get("level", 50))))
    ok = audio_engine.set_brightness(level)
    if not ok:
        return jsonify(error="Brightness unavailable (laptop/DDC monitors only)"), 500
    return jsonify(ok=True)
# ---------------------------------------------------------------- sound, speech, webcam
@app.post("/api/sound")
@login_required
def api_sound():
    kind = (request.get_json(silent=True) or {}).get("kind", "beep")
    audio_engine.play_sound("alarm" if kind == "alarm" else "beep")
    return jsonify(ok=True, msg="Playing sound on PC")
@app.post("/api/speak")
@login_required
def api_speak():
    text = str((request.get_json(silent=True) or {}).get("text", ""))[:300]
    if not text:
        return jsonify(error="empty"), 400
    audio_engine.speak_text(text)
    return jsonify(ok=True, msg="Speaking on PC")
@app.get("/api/webcam")
@login_required
def api_webcam():
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        for _ in range(5):  # let exposure settle
            cap.read()
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("no camera")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return Response(buf.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as e:
        return jsonify(error=f"Webcam unavailable: {e}"), 500
def generate_webcam_stream():
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.08)
                    continue
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if not ok:
                    continue
                yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
                time.sleep(0.04)
        finally:
            cap.release()
    except GeneratorExit:
        pass
    except Exception:
        pass
@app.get("/api/stream/webcam")
@login_required
def api_stream_webcam():
    return Response(generate_webcam_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")
# ---------------------------------------------------------------- tap-to-click on the live screen
@app.post("/api/mouse/click_at")
@login_required
def api_click_at():
    d = request.get_json(silent=True) or {}
    fx = max(0.0, min(1.0, float(d.get("x", 0))))
    fy = max(0.0, min(1.0, float(d.get("y", 0))))
    input_engine.click_absolute(fx, fy, right=bool(d.get("right")), double=bool(d.get("double")))
    return jsonify(ok=True)
# ---------------------------------------------------------------- saved commands
@app.get("/api/commands")
@login_required
def api_commands():
    return jsonify(list(CFG.get("commands", {}).keys()))
@app.post("/api/command")
@login_required
def api_command():
    cmd = CFG.get("commands", {}).get((request.get_json(silent=True) or {}).get("name"))
    if not cmd:
        return jsonify(error="Unknown command"), 400
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors="replace", timeout=30)
        return jsonify(output=((r.stdout or "") + (r.stderr or ""))[-2000:] or "(done, no output)")
    except subprocess.TimeoutExpired:
        return jsonify(error="Timed out after 30s"), 400
# ---------------------------------------------------------------- start with PC
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LINUX_AUTOSTART = Path.home() / ".config" / "autostart" / "remotepc.desktop"
def autostart_command():
    if getattr(sys, "frozen", False):
        return f'cmd /c start "" /min "{sys.executable}"'
    pyw = Path(sys.executable).with_name("pythonw.exe")  # no console window
    exe = pyw if pyw.exists() else Path(sys.executable)
    return f'"{exe}" "{Path(__file__).resolve()}"'
def autostart_enabled():
    if IS_WIN:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                try:
                    winreg.QueryValueEx(k, "Project-X-Nano")
                    return True
                except OSError:
                    winreg.QueryValueEx(k, "RemotePC")
                    return True
        except OSError:
            pass
        return subprocess.run(["schtasks", "/Query", "/TN", "Project-X-Nano"], capture_output=True).returncode == 0
    return LINUX_AUTOSTART.exists()
def set_autostart(on):
    if IS_WIN:
        import winreg
        def drop_registry():
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                for name in ["Project-X-Nano", "RemotePC"]:
                    try:
                        winreg.DeleteValue(k, name)
                    except FileNotFoundError:
                        pass
        def drop_task():
            for name in ["Project-X-Nano", "RemotePC"]:
                subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
            subprocess.run(["schtasks", "/Delete", "/TN", "RemotePC", "/F"], capture_output=True)
        drop_registry()
        drop_task()
        if on and CFG.get("autostart_as_admin"):
            if not is_admin():
                raise ValueError("Start Project-X-Nano as Administrator once, then enable this (needed to create the admin startup task)")
            r = subprocess.run(
                ["schtasks", "/Create", "/TN", "Project-X-Nano", "/TR", autostart_command(),
                 "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise ValueError("schtasks failed: " + (r.stderr or r.stdout)[:200])
        elif on:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "Project-X-Nano", 0, winreg.REG_SZ, autostart_command())
    elif IS_MAC:
        raise ValueError("Not supported on macOS")
    elif on:
        LINUX_AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        LINUX_AUTOSTART.write_text(
            f"[Desktop Entry]\nType=Application\nName=Project-X-Nano\nExec={sys.executable} {Path(__file__).resolve()}\n"
        )
    else:
        LINUX_AUTOSTART.unlink(missing_ok=True)
@app.get("/api/autostart")
@login_required
def api_autostart_get():
    return jsonify(enabled=autostart_enabled())
@app.post("/api/autostart")
@login_required
def api_autostart_set():
    try:
        set_autostart(bool((request.get_json(silent=True) or {}).get("enabled")))
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, enabled=autostart_enabled(), msg="Start with PC: " + ("on" if autostart_enabled() else "off"))
@app.post("/api/system/uninstall")
@login_required
def api_system_uninstall():
    data = request.get_json(silent=True) or {}
    pw = data.get("password", "")
    if not pw or not check_password_hash(CFG["password_hash"], pw):
        return jsonify(error="Master password confirmation required to authorize uninstallation"), 403

    try:
        if IS_WIN:
            # 1. Place lock file to disarm watchdog
            try:
                if "LOCALAPPDATA" in os.environ:
                    (Path(os.environ["LOCALAPPDATA"]) / "Project-X-Nano" / "uninstalling.lock").touch()
                (BASE / "uninstalling.lock").touch()
            except Exception:
                pass

            # 2. Terminate watchdog and tunnel
            subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%watchdog%'\" | Invoke-CimMethod -MethodName Terminate"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)

            # 3. Remove Run keys
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                for name in ["Project-X-Nano", "Project-X-Nano-Watchdog", "RemotePC"]:
                    try:
                        winreg.DeleteValue(k, name)
                    except FileNotFoundError:
                        pass
            for name in ["Project-X-Nano", "Project-X-Nano-Watchdog", "RemotePC"]:
                subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], capture_output=True)
        elif IS_LINUX:
            try:
                (Path.home() / ".local/share/project-x-nano/uninstalling.lock").touch(exist_ok=True)
                (BASE / "uninstalling.lock").touch(exist_ok=True)
                subprocess.run(["systemctl", "--user", "stop", "project-x-nano.service"], capture_output=True)
                subprocess.run(["systemctl", "--user", "disable", "project-x-nano.service"], capture_output=True)
                subprocess.run(["pkill", "-9", "-f", "server.py"], capture_output=True)
                subprocess.run(["pkill", "-9", "-f", "watchdog"], capture_output=True)
                subprocess.run(["pkill", "-9", "-f", "cloudflared"], capture_output=True)
                (Path.home() / ".config/systemd/user/project-x-nano.service").unlink(missing_ok=True)
                (Path.home() / ".config/autostart/project-x-nano.desktop").unlink(missing_ok=True)
                inst = Path.home() / ".local/share/project-x-nano"
                if inst.exists():
                    shutil.rmtree(inst, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass

    def delayed_exit():
        time.sleep(1.0)
        try:
            cleanup_cmds = ["timeout /t 2 /nobreak >nul"]
            target_dirs = []
            if "LOCALAPPDATA" in os.environ:
                target_dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Project-X-Nano")
                target_dirs.append(Path(os.environ["LOCALAPPDATA"]) / "RemotePC")
            target_dirs.append(Path(r"C:\RemotePC"))
            for d in target_dirs:
                if d.exists():
                    cleanup_cmds.append(f'rmdir /s /q "{d}"')
            full_cleanup = " & ".join(cleanup_cmds)
            subprocess.Popen(
                f'cmd.exe /c "{full_cleanup}"',
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            )
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return jsonify(ok=True, msg="Project-X-Nano completely uninstalled. All files, folders, registry keys, and background tasks deleted.")
@app.get("/favicon.ico")
@app.get("/favicon.png")
def api_favicon():
    fav = BASE / "favicon.png"
    if fav.exists():
        return send_file(fav, mimetype="image/png")
    return ("", 204)
@app.get("/icon-192.png")
def api_icon192():
    ic = BASE / "icon-192.png"
    if ic.exists():
        return send_file(ic, mimetype="image/png")
    return ("", 204)
# ---------------------------------------------------------------- remote terminal (admin shell)
TERM = {"cwd": str(Path.home())}
TERM_UNLOCK_SECONDS = 600
def is_admin():
    try:
        if IS_WIN:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False
def audit(text, details=None):
    try:
        ip = get_client_ip()
    except Exception:
        ip = "127.0.0.1"
    audit_module.write_audit(BASE / "audit.log", ip, text, details=details)
def term_guard():
    if not CFG.get("terminal_enabled"):
        return jsonify(error='Terminal is disabled. On the PC, set "terminal_enabled": true in config.json and restart.'), 403
    try:
        if ipaddress.ip_address(request.remote_addr).is_global:
            return jsonify(error="Terminal only works from your home network or Tailscale, not the open internet"), 403
    except ValueError:
        return jsonify(error="bad address"), 403
    return None
@app.get("/api/terminal/status")
@login_required
def api_term_status():
    return jsonify(
        enabled=bool(CFG.get("terminal_enabled")), admin=is_admin(),
        unlocked=time.time() < session.get("term_until", 0), cwd=TERM["cwd"],
        shells=["cmd", "powershell"] if IS_WIN else ["bash"],
    )
@app.post("/api/terminal/unlock")
@login_required
def api_term_unlock():
    if (g := term_guard()):
        return g
    client_ip = get_client_ip()
    key = "term:" + client_ip
    count, locked = FAILS.get(key, (0, 0))
    if time.time() < locked:
        return jsonify(error="Too many attempts. Wait a minute."), 429
    pw = (request.get_json(silent=True) or {}).get("password", "")
    if not (pw and check_password_hash(CFG["password_hash"], pw)):
        count += 1
        FAILS[key] = (count, time.time() + 60 if count >= 3 else 0)
        audit("terminal unlock FAILED")
        push_alert(f"Failed terminal unlock from {client_ip}")
        time.sleep(1)
        return jsonify(error="Wrong password"), 403
    FAILS.pop(key, None)
    session["term_until"] = time.time() + TERM_UNLOCK_SECONDS
    audit("terminal unlocked")
    push_alert(f"Terminal unlocked from {client_ip}")
    return jsonify(ok=True, msg="Terminal unlocked for 10 minutes")
@app.post("/api/terminal/lock")
@login_required
def api_term_lock():
    session.pop("term_until", None)
    return jsonify(ok=True, msg="Terminal locked")
@app.post("/api/terminal/run")
@login_required
def api_term_run():
    if (g := term_guard()):
        return g
    if time.time() >= session.get("term_until", 0):
        return jsonify(error="Terminal locked: enter your password again", locked=True), 403
    d = request.get_json(silent=True) or {}
    cmd = str(d.get("cmd", "")).strip()[:2000]
    shell = d.get("shell", "cmd")
    if not cmd:
        return jsonify(error="empty command"), 400
    audit(f"[{shell}] {cmd}")
    out, code, updated_cwd = term_engine.run_command(cmd, shell=shell)
    TERM["cwd"] = updated_cwd
    session["term_until"] = time.time() + TERM_UNLOCK_SECONDS
    return jsonify(output=out, cwd=TERM["cwd"], code=code)
# ---------------------------------------------------------------- installable app (PWA)
@app.get("/manifest.json")
def manifest():
    return jsonify(
        name="Remote PC", short_name="RemotePC", start_url="/", display="standalone",
        background_color="#0f1115", theme_color="#0f1115",
        icons=[{"src": f"/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png", "purpose": "any maskable"} for s in (192, 512)],
    )
@app.get("/sw.js")
def service_worker():
    js = "self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('fetch',()=>{});"
    return Response(js, mimetype="application/javascript")
@app.get("/icon-<int:size>.png")
def icon(size):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return "", 404
    size = 192 if size < 400 else 512
    img = Image.new("RGB", (size, size), "#0f1115")
    d = ImageDraw.Draw(img)
    m = size // 6
    d.rounded_rectangle([m, m * 1.4, size - m, size - m * 2], size // 22, outline="#4f8cff", width=max(4, size // 24))
    d.rectangle([size // 2 - m // 2, size - m * 2, size // 2 + m // 2, size - m * 1.3], fill="#4f8cff")
    d.rectangle([size // 2 - m, size - m * 1.3, size // 2 + m, size - m * 1.0], fill="#4f8cff")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})
# ---------------------------------------------------------------- device discovery
def scan_device(ip, port=8765):
    dev = fleet_engine.probe_device(ip, port)
    if dev:
        return {"ip": dev["ip"], "port": dev["port"], "name": dev["host"], "url": dev["url"]}
    return None
def discover_network_devices():
    found = fleet_engine.discover_local_subnet(lan_ip())
    return [{"ip": d["ip"], "port": d["port"], "name": d["host"], "url": d["url"]} for d in found]
@app.get("/api/discover")
@login_required
def api_discover():
    try:
        devices = discover_network_devices()
        return jsonify(devices=devices, my_ip=lan_ip(), my_host=platform.node())
    except Exception as e:
        return jsonify(error=str(e), devices=[]), 500
# ---------------------------------------------------------------- fleet management (50-100+ PCs)
def check_fleet_node(node):
    return fleet_engine.check_node_health(node)
@app.get("/api/fleet")
@login_required
def api_fleet():
    fleet_nodes = CFG.get("fleet", [])
    my_info = {
        "id": "local",
        "name": f"{platform.node()} (This PC)",
        "url": f"http://{lan_ip()}:{CFG['port']}",
        "group": "Local",
        "online": True,
        "local": True,
        "cpu": psutil.cpu_percent(),
        "ram": bridge.get_memory_stats()[2] or psutil.virtual_memory().percent,
    }
    results = [my_info]
    if fleet_nodes:
        max_workers = min(50, max(1, len(fleet_nodes)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            statuses = list(pool.map(check_fleet_node, fleet_nodes))
            results.extend(statuses)
    return jsonify(fleet=results, count=len(results))
@app.post("/api/fleet/add")
@login_required
def api_fleet_add():
    d = request.get_json(silent=True) or {}
    url = str(d.get("url", "")).strip().rstrip("/")
    name = str(d.get("name", "")).strip()
    group = str(d.get("group", "Default")).strip() or "Default"
    if not url:
        return jsonify(error="URL required (e.g. http://192.168.1.50:8765)"), 400
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    if not name:
        name = url
    fleet = CFG.setdefault("fleet", [])
    for item in fleet:
        if item.get("url") == url:
            return jsonify(error="Device already in fleet"), 400
    node_id = secrets.token_hex(4)
    fleet.append({"id": node_id, "name": name, "url": url, "group": group})
    save_cfg()
    return jsonify(ok=True, msg=f"Added '{name}' to fleet", id=node_id)
@app.post("/api/fleet/remove")
@login_required
def api_fleet_remove():
    d = request.get_json(silent=True) or {}
    node_id = str(d.get("id", "")).strip()
    fleet = CFG.get("fleet", [])
    CFG["fleet"] = [f for f in fleet if f.get("id") != node_id]
    save_cfg()
    return jsonify(ok=True, msg="Removed from fleet")
@app.post("/api/fleet/broadcast")
@login_required
def api_fleet_broadcast():
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    fleet = CFG.get("fleet", [])
    if action not in ["lock", "sleep", "restart", "shutdown"]:
        return jsonify(error="Invalid action"), 400
    sent = fleet_engine.broadcast_action(fleet, action, delay=10)
    return jsonify(ok=True, msg=f"Broadcasted '{action}' to {sent} fleet PCs")
# ---------------------------------------------------------------- UI
PAGE = r"""<!doctype html><html lang="en" data-theme="cyber"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Project-X-Nano</title>
<link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#080b14">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Project-X-Nano">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* ==========================================================================
   CSS CUSTOM PROPERTIES & COLOR THEMES
   ========================================================================== */
:root, [data-theme="cyber"] {
  --bg-base: #07090e;
  --bg-gradient: radial-gradient(circle at 50% 0%, #111a2e 0%, #07090e 75%);
  --surface-card: rgba(15, 22, 38, 0.75);
  --surface-card-hover: rgba(22, 32, 54, 0.85);
  --surface-inset: #090e1a;
  --border-card: rgba(59, 130, 246, 0.16);
  --border-card-hover: rgba(59, 130, 246, 0.35);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --accent: #3b82f6;
  --accent-secondary: #6366f1;
  --accent-glow: rgba(59, 130, 246, 0.4);
  --accent-gradient: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  --green: #10b981;
  --green-bg: rgba(16, 185, 129, 0.12);
  --green-glow: rgba(16, 185, 129, 0.3);
  --red: #ef4444;
  --red-bg: rgba(239, 68, 68, 0.12);
  --amber: #f59e0b;
  --btn-bg: #151d30;
  --btn-bg-hover: #1e2942;
  --btn-border: rgba(255, 255, 255, 0.09);
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', Consolas, Monaco, monospace;
}

[data-theme="oled"] {
  --bg-base: #000000;
  --bg-gradient: #000000;
  --surface-card: #0a0a0a;
  --surface-card-hover: #121212;
  --surface-inset: #050505;
  --border-card: rgba(255, 255, 255, 0.15);
  --border-card-hover: rgba(255, 255, 255, 0.3);
  --text-main: #ffffff;
  --text-muted: #a1a1aa;
  --accent: #22c55e;
  --accent-secondary: #10b981;
  --accent-glow: rgba(34, 197, 94, 0.35);
  --accent-gradient: linear-gradient(135deg, #22c55e 0%, #10b981 100%);
  --green: #22c55e;
  --green-bg: rgba(34, 197, 94, 0.15);
  --btn-bg: #111111;
  --btn-bg-hover: #1f1f1f;
  --btn-border: rgba(255, 255, 255, 0.18);
}

[data-theme="synthwave"] {
  --bg-base: #0a0514;
  --bg-gradient: radial-gradient(circle at 50% 0%, #200f38 0%, #0a0514 80%);
  --surface-card: rgba(24, 13, 43, 0.75);
  --surface-card-hover: rgba(34, 19, 61, 0.85);
  --surface-inset: #0e071c;
  --border-card: rgba(168, 85, 247, 0.22);
  --border-card-hover: rgba(236, 72, 153, 0.4);
  --text-main: #faf5ff;
  --text-muted: #c084fc;
  --accent: #d946ef;
  --accent-secondary: #8b5cf6;
  --accent-glow: rgba(217, 70, 239, 0.45);
  --accent-gradient: linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%);
  --green: #06b6d4;
  --green-bg: rgba(6, 182, 212, 0.15);
  --btn-bg: #211138;
  --btn-bg-hover: #2e184f;
  --btn-border: rgba(168, 85, 247, 0.25);
}

[data-theme="matrix"] {
  --bg-base: #030804;
  --bg-gradient: radial-gradient(circle at 50% 0%, #0a1f0d 0%, #030804 80%);
  --surface-card: rgba(7, 24, 10, 0.8);
  --surface-card-hover: rgba(11, 36, 16, 0.9);
  --surface-inset: #041006;
  --border-card: rgba(34, 197, 94, 0.25);
  --border-card-hover: rgba(34, 197, 94, 0.5);
  --text-main: #dcfce7;
  --text-muted: #86efac;
  --accent: #22c55e;
  --accent-secondary: #16a34a;
  --accent-glow: rgba(34, 197, 94, 0.5);
  --accent-gradient: linear-gradient(135deg, #22c55e 0%, #15803d 100%);
  --green: #22c55e;
  --green-bg: rgba(34, 197, 94, 0.2);
  --btn-bg: #0c2b12;
  --btn-bg-hover: #123d1b;
  --btn-border: rgba(34, 197, 94, 0.3);
}

[data-theme="nord"] {
  --bg-base: #0b1120;
  --bg-gradient: radial-gradient(circle at 50% 0%, #1e293b 0%, #0b1120 80%);
  --surface-card: rgba(17, 24, 39, 0.8);
  --surface-card-hover: rgba(30, 41, 59, 0.9);
  --surface-inset: #080d1a;
  --border-card: rgba(56, 189, 248, 0.2);
  --border-card-hover: rgba(56, 189, 248, 0.4);
  --text-main: #f0f9ff;
  --text-muted: #94a3b8;
  --accent: #38bdf8;
  --accent-secondary: #0ea5e9;
  --accent-glow: rgba(56, 189, 248, 0.4);
  --accent-gradient: linear-gradient(135deg, #38bdf8 0%, #0284c7 100%);
  --green: #34d399;
  --green-bg: rgba(52, 211, 153, 0.15);
  --btn-bg: #1e293b;
  --btn-bg-hover: #334155;
  --btn-border: rgba(255, 255, 255, 0.1);
}

[data-theme="crimson"] {
  --bg-base: #0c0507;
  --bg-gradient: radial-gradient(circle at 50% 0%, #260a12 0%, #0c0507 80%);
  --surface-card: rgba(28, 11, 17, 0.8);
  --surface-card-hover: rgba(41, 16, 25, 0.9);
  --surface-inset: #120609;
  --border-card: rgba(244, 63, 94, 0.25);
  --border-card-hover: rgba(244, 63, 94, 0.5);
  --text-main: #fff1f2;
  --text-muted: #fda4af;
  --accent: #f43f5e;
  --accent-secondary: #e11d48;
  --accent-glow: rgba(244, 63, 94, 0.45);
  --accent-gradient: linear-gradient(135deg, #f43f5e 0%, #be123c 100%);
  --green: #10b981;
  --green-bg: rgba(16, 185, 129, 0.15);
  --btn-bg: #240c14;
  --btn-bg-hover: #36121e;
  --btn-border: rgba(244, 63, 94, 0.28);
}

/* ==========================================================================
   GLOBAL RESET & TYPOGRAPHY
   ========================================================================== */
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body {
  margin: 0;
  background: var(--bg-base);
  background-image: var(--bg-gradient);
  background-attachment: fixed;
  color: var(--text-main);
  font: 14px/1.5 var(--font-sans);
  padding: 14px 16px 40px;
  max-width: 980px;
  margin: auto;
  min-height: 100vh;
  transition: background 0.3s ease, color 0.3s ease;
}

/* ==========================================================================
   HEADER & NAVIGATION BAR
   ========================================================================== */
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0 16px;
  border-bottom: 1px solid var(--border-card);
  margin-bottom: 16px;
  gap: 12px;
}
.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 19px;
  font-weight: 800;
  letter-spacing: -0.02em;
}
.brand-badge {
  font-size: 10px;
  font-weight: 800;
  padding: 3px 9px;
  border-radius: 9999px;
  background: var(--accent-gradient);
  color: #fff;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  box-shadow: 0 2px 10px var(--accent-glow);
}
.pulse-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 12px var(--green);
  display: inline-block;
  animation: pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
@keyframes pulse-ring {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.pill-select {
  background: var(--surface-card);
  border: 1px solid var(--border-card);
  color: var(--text-main);
  padding: 6px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  outline: none;
  transition: all 0.2s ease;
}
.pill-select:hover, .pill-select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-glow);
}

/* Reconnection Banner */
#reconnectBanner {
  display: none;
  position: sticky;
  top: 10px;
  z-index: 9998;
  background: rgba(245, 158, 11, 0.95);
  backdrop-filter: blur(12px);
  color: #000;
  padding: 9px 18px;
  border-radius: 14px;
  font-weight: 700;
  font-size: 13px;
  text-align: center;
  box-shadow: 0 6px 20px rgba(0,0,0,0.4);
  margin-bottom: 12px;
  animation: pulse-ring 1.5s infinite;
}

/* ==========================================================================
   NAVIGATION TABS
   ========================================================================== */
.nav-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 4px 2px 12px;
  margin-bottom: 16px;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.nav-tabs::-webkit-scrollbar { display: none; }
.nav-tab {
  flex: 0 0 auto;
  background: var(--surface-card);
  backdrop-filter: blur(14px);
  border: 1px solid var(--border-card);
  color: var(--text-muted);
  padding: 9px 16px;
  border-radius: 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.nav-tab:hover {
  background: var(--surface-card-hover);
  color: var(--text-main);
  border-color: var(--border-card-hover);
}
.nav-tab.active {
  background: var(--accent-gradient);
  border-color: transparent;
  color: #ffffff;
  box-shadow: 0 4px 16px var(--accent-glow);
}

/* ==========================================================================
   CARDS & GRIDS
   ========================================================================== */
.card {
  background: var(--surface-card);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-card);
  border-radius: 18px;
  padding: 18px;
  margin-bottom: 16px;
  box-shadow: 0 10px 30px -6px rgba(0,0,0,0.5);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
}
.card:hover {
  border-color: var(--border-card-hover);
}
.card h2 {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 0 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card h2 span { display: inline-flex; align-items: center; gap: 8px; }

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.grid-4 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 768px) {
  .grid-2, .grid-4 { grid-template-columns: 1fr; }
  .grid { grid-template-columns: repeat(2, 1fr); }
  .card { padding: 14px; border-radius: 15px; }
}

/* ==========================================================================
   BUTTONS, INPUTS & CONTROLS
   ========================================================================== */
button, .btn {
  font: inherit;
  font-family: var(--font-sans);
  border-radius: 12px;
  border: 1px solid var(--btn-border);
  padding: 10px 14px;
  background: var(--btn-bg);
  color: var(--text-main);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  text-decoration: none;
  user-select: none;
}
button:hover, .btn:hover {
  background: var(--btn-bg-hover);
  border-color: rgba(255,255,255,0.2);
  transform: translateY(-1px);
}
button:active, .btn:active {
  transform: translateY(1px) scale(0.98);
}
button.acc, .btn.acc {
  background: var(--accent-gradient);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 14px var(--accent-glow);
}
button.acc:hover, .btn.acc:hover {
  filter: brightness(1.12);
}
button.red, .btn.red {
  background: var(--red-bg);
  color: var(--red);
  border-color: rgba(239, 68, 68, 0.3);
}
button.red:hover, .btn.red:hover {
  background: rgba(239, 68, 68, 0.25);
}
button.green, .btn.green {
  background: var(--green-bg);
  color: var(--green);
  border-color: rgba(16, 185, 129, 0.3);
}

input, textarea, select {
  font: inherit;
  font-family: var(--font-sans);
  width: 100%;
  background: var(--surface-inset);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 10px 14px;
  color: var(--text-main);
  outline: none;
  font-size: 13px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
input:focus, textarea:focus, select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
.row {
  display: flex;
  gap: 10px;
  margin-top: 10px;
  align-items: center;
}
.row > * { flex: 1; }

/* Sliders */
input[type=range] {
  -webkit-appearance: none;
  appearance: none;
  background: var(--btn-bg);
  height: 8px;
  border-radius: 6px;
  padding: 0;
  cursor: pointer;
  border: none;
}
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 2px 10px var(--accent-glow);
  cursor: pointer;
  transition: transform 0.1s ease;
}
input[type=range]::-webkit-slider-thumb:hover {
  transform: scale(1.15);
}

/* ==========================================================================
   METRICS & HARDWARE GAUGES
   ========================================================================== */
.stat-box {
  background: var(--surface-inset);
  border: 1px solid var(--border-card);
  border-radius: 14px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.stat-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.stat-header span:last-child {
  color: var(--text-main);
  font-family: var(--font-mono);
}
.bar {
  height: 8px;
  background: var(--btn-bg);
  border-radius: 6px;
  overflow: hidden;
}
.bar > i {
  display: block;
  height: 100%;
  background: var(--accent-gradient);
  border-radius: 6px;
  transition: width 0.4s ease;
}
.bar-ram > i { background: linear-gradient(90deg, #8b5cf6, #ec4899); }
.bar-disk > i { background: linear-gradient(90deg, #10b981, #06b6d4); }

.proc {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 12px;
  background: var(--surface-inset);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  margin-bottom: 6px;
  font-size: 13px;
  transition: border-color 0.15s ease;
}
.proc:hover { border-color: var(--border-card-hover); }

.badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 8px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.badge-green { background: var(--green-bg); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.25); }
.badge-red { background: var(--red-bg); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.25); }

/* Host server banner pill */
.server-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--surface-inset);
  border: 1px solid var(--border-card);
  padding: 6px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--accent);
}

/* Toast Alerts */
#toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.96);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-card-hover);
  color: #fff;
  padding: 10px 22px;
  border-radius: 40px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 12px 36px rgba(0,0,0,0.6);
  display: none;
  z-index: 9999;
}

/* ==========================================================================
   IMMERSIVE FULLSCREEN CONTAINER FOR SCREEN STREAM
   ========================================================================== */
.screen-wrapper {
  position: relative;
  background: #000;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--border-card);
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.screen-wrapper:fullscreen {
  width: 100vw;
  height: 100vh;
  border-radius: 0;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
}
.screen-wrapper:fullscreen img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  margin: 0;
}
.screen-overlay-bar {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.88);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 30px;
  padding: 6px 14px;
  display: flex;
  gap: 8px;
  align-items: center;
  z-index: 100;
  opacity: 0.95;
  transition: opacity 0.3s ease;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
}
.screen-wrapper:fullscreen .screen-overlay-bar {
  opacity: 0;
}
.screen-wrapper:fullscreen:hover .screen-overlay-bar {
  opacity: 1;
}

img { width: 100%; border-radius: 12px; margin-top: 8px; display: block; }

/* ==========================================================================
   ENHANCED MODERN MOTION & GLASSMORPHISM UPGRADES
   ========================================================================== */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(14px) scale(0.99); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes pulseGlowRing {
  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.45); }
  70% { box-shadow: 0 0 0 10px rgba(59, 130, 246, 0); }
  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}

@keyframes floatSoft {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

@keyframes gradientShift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.tab-content {
  animation: fadeInUp 0.32s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.card {
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.28s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.28s ease !important;
}

.card:hover {
  border-color: var(--border-card-hover) !important;
  box-shadow: 0 16px 36px -8px rgba(0, 0, 0, 0.65), 0 0 24px -4px rgba(59, 130, 246, 0.12) !important;
}

.stat-box {
  transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
}

.stat-box:hover {
  transform: translateY(-2px);
  border-color: var(--border-card-hover);
  box-shadow: 0 6px 18px -4px rgba(0,0,0,0.4);
}

button, .btn {
  position: relative;
  overflow: hidden;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

button:hover, .btn:hover {
  transform: translateY(-1.5px);
  filter: brightness(1.08);
}

button:active, .btn:active {
  transform: translateY(1px) scale(0.98);
}

button.acc, .btn.acc {
  background-size: 200% 200%;
  animation: gradientShift 6s ease infinite;
}

.nav-tab {
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.nav-tab:hover {
  transform: translateY(-1px);
  color: var(--text-main) !important;
  border-color: var(--border-card-hover) !important;
}

.nav-tab.active {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px -2px var(--accent-glow) !important;
}

.pulse-dot {
  animation: pulseGlowRing 2s infinite !important;
}

.brand-badge {
  background: var(--accent-gradient);
  background-size: 200% 200%;
  animation: gradientShift 8s ease infinite;
  box-shadow: 0 2px 10px var(--accent-glow);
}

#login {
  animation: fadeInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.server-pill {
  transition: background 0.2s ease, border-color 0.2s ease;
}

.server-pill:hover {
  border-color: var(--accent);
}
</style></head><body>

<!-- Connection Reconnect Banner -->
<div id="reconnectBanner">🔄 Reconnecting to Host PC Server...</div>

<!-- Login Modal -->
<div id="login" class="card" style="display:none;max-width:400px;margin:80px auto;text-align:center">
  <div style="margin-bottom:18px">
    <img src="/favicon.png" style="width:58px;height:58px;margin:0 auto 12px;border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,0.4)" alt="Logo">
    <h1 style="font-size:22px;margin:0;font-weight:800">Project-X-Nano</h1>
    <p style="color:var(--text-muted);font-size:13px;margin:6px 0 0">Dedicated Host Controller &amp; Fleet Hub</p>
  </div>
  <input id="pw" type="password" placeholder="Enter Master Password" style="margin-bottom:12px;text-align:center">
  
  <div id="login2faBox" style="display:none;margin-bottom:12px">
    <div style="font-size:12px;color:var(--accent);margin-bottom:6px">🔐 2FA Enabled - Enter Authenticator Code:</div>
    <input id="loginTotp" type="text" placeholder="6-digit code" maxlength="6" style="text-align:center;font-size:16px;letter-spacing:4px">
  </div>

  <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:14px;font-size:12px;color:var(--text-muted)">
    <input type="checkbox" id="chkRemember" checked style="width:auto;margin:0;cursor:pointer">
    <label for="chkRemember" style="cursor:pointer">Remember &amp; Auto-Connect</label>
  </div>
  
  <button class="acc" style="width:100%" onclick="login()">⚡ Connect to PC</button>
  
  <div style="margin-top:16px;display:flex;justify-content:center;gap:12px">
    <a href="/download/apk" style="color:var(--accent);font-size:12px;text-decoration:none;display:inline-flex;align-items:center;gap:6px">
      <span>📱</span> Download Android APK
    </a>
  </div>
</div>

<!-- Main Application -->
<div id="main" style="display:none">
  <!-- Top App Header -->
  <header class="app-header">
    <div class="app-brand">
      <img src="/favicon.png" style="width:28px;height:28px;border-radius:8px;vertical-align:middle" alt="Logo">
      <span id="host">Project-X-Nano</span>
      <span class="brand-badge">NANO HOST</span>
    </div>
    
    <div class="header-actions">
      <!-- Quick Theme Switcher in Header -->
      <select class="pill-select" id="themePickerHeader" onchange="setTheme(this.value)">
        <option value="cyber">⚡ Cyber Dark</option>
        <option value="oled">🖤 OLED Black</option>
        <option value="synthwave">🔮 Synthwave</option>
        <option value="matrix">💻 Matrix Green</option>
        <option value="nord">❄ Arctic Nord</option>
        <option value="crimson">🩸 Crimson Red</option>
      </select>

      <!-- Fullscreen Dashboard Button -->
      <button onclick="toggleDashboardFullscreen()" class="btn" style="padding:6px 11px;font-size:12px" title="Toggle Fullscreen Dashboard">
        <span id="fsIcon">⛶</span> Fullscreen
      </button>

      <a href="/download/apk" class="btn" style="padding:6px 11px;font-size:12px">
        <span>📱</span> APK
      </a>
      
      <span class="pulse-dot"></span>
      <span style="font-size:12px;color:var(--green);font-weight:700">ONLINE</span>
      <button style="padding:6px 11px;font-size:12px" onclick="logout()">Log out</button>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <nav class="nav-tabs">
    <button class="nav-tab active" onclick="showTab('overview', this)">📊 Overview</button>
    <button class="nav-tab" onclick="showTab('server', this)">🖥️ Host Backend</button>
    <button class="nav-tab" onclick="showTab('fleet', this)">👥 Fleet (<span id="tabFleetCount">1</span>)</button>
    <button class="nav-tab" onclick="showTab('screen', this)">📺 Live Screen &amp; Cam</button>
    <button class="nav-tab" onclick="showTab('controls', this)">🎮 Remote Controls</button>
    <button class="nav-tab" onclick="showTab('procs', this)">⚡ Processes</button>
    <button class="nav-tab" onclick="showTab('ports', this)">🌐 Ports</button>
    <button class="nav-tab" onclick="showTab('services', this)">⚙️ Services</button>
    <button class="nav-tab" onclick="showTab('files', this)">📁 Files &amp; Drives</button>
    <button class="nav-tab" onclick="showTab('terminal', this)">💻 Terminal</button>
    <button class="nav-tab" onclick="showTab('security', this)">🛡️ Security &amp; Audit</button>
  </nav>

  <!-- 1. OVERVIEW TAB -->
  <div id="tab-overview" class="tab-content">
    <div class="grid-2">
      <!-- System Telemetry -->
      <div class="card">
        <h2>⚡ System Health</h2>
        <div class="stat-box">
          <div class="stat-header"><span>CPU Load</span><span id="cpuT">0%</span></div>
          <div class="bar"><i id="cpu" style="width:0%"></i></div>
        </div>
        <div class="stat-box">
          <div class="stat-header"><span>Memory Usage</span><span id="ramT">0%</span></div>
          <div class="bar bar-ram"><i id="ram" style="width:0%"></i></div>
        </div>
        <div class="stat-box">
          <div class="stat-header"><span>Disk Space</span><span id="diskT">0%</span></div>
          <div class="bar bar-disk"><i id="disk" style="width:0%"></i></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted);margin-top:10px">
          <span id="osT">Windows</span>
          <span id="batT">🔋 Checking…</span>
        </div>
      </div>
      <!-- Quick Commands -->
      <div class="card">
        <h2>⚡ Quick Commands</h2>
        <div class="grid" id="cmds"></div>
        <pre id="cmdout" style="white-space:pre-wrap;font-size:11px;font-family:var(--font-mono);color:var(--text-muted);background:var(--surface-inset);border:1px solid var(--border-card);border-radius:12px;padding:10px;max-height:140px;overflow:auto;margin:10px 0 0"></pre>
      </div>
    </div>
    <!-- App Launchers & Web -->
    <div class="card">
      <h2>🚀 App Launchers &amp; Web Navigation</h2>
      <div class="row" style="margin-bottom:12px">
        <input id="url" placeholder="Open website on PC (e.g. youtube.com)">
        <button class="acc" onclick="openUrl()" style="flex:0 0 120px">🌐 Open Link</button>
      </div>
      <div class="grid" id="apps"></div>
    </div>
    <!-- On-screen Message -->
    <div class="card">
      <h2>💬 Push Message to PC Screen</h2>
      <div class="row">
        <input id="msg" placeholder="Display message banner on PC screen…">
        <button class="acc" onclick="sendMsg()" style="flex:0 0 130px">Send Message</button>
      </div>
    </div>
  </div>

  <!-- 2. HOST BACKEND SERVER TAB -->
  <div id="tab-server" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>🖥️ Host Backend Server Configuration</span>
        <span class="badge badge-green">RUNNING AS BACKEND</span>
      </h2>
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 14px">
        Your PC is operating as the central master server for Project-X-Nano. Connect to this PC from your phone, laptop, or tablet.
      </p>

      <div class="grid-2" style="margin-bottom:16px">
        <div class="stat-box">
          <div class="stat-header"><span>Local Network Access (Wi-Fi)</span></div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
            <span class="server-pill" id="srvLanUrl">http://...:8765</span>
            <button class="btn" style="padding:4px 10px;font-size:11px" onclick="copyText($('srvLanUrl').textContent)">📋 Copy</button>
          </div>
          <small style="color:var(--text-muted);display:block;margin-top:6px">Open this URL in your phone browser when connected to same Wi-Fi.</small>
        </div>

        <div class="stat-box">
          <div class="stat-header"><span>Localhost Loopback</span></div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
            <span class="server-pill" id="srvLoopbackUrl">http://127.0.0.1:8765</span>
            <button class="btn" style="padding:4px 10px;font-size:11px" onclick="copyText('http://127.0.0.1:8765')">📋 Copy</button>
          </div>
          <small style="color:var(--text-muted);display:block;margin-top:6px">Direct local access on this host PC.</small>
        </div>
      </div>

      <div class="stat-box" style="margin-bottom:16px">
        <div class="stat-header"><span>Public Internet Tunnel Access (Cloudflare Tunnel)</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
          <span class="server-pill" id="srvTunnelUrl" style="word-break:break-all">Checking public tunnel...</span>
          <button class="btn acc" style="padding:4px 10px;font-size:11px" onclick="copyText($('srvTunnelUrl').textContent)">📋 Copy Link</button>
        </div>
        <small style="color:var(--text-muted);display:block;margin-top:6px">Use this link to access your PC securely from anywhere in the world without port forwarding.</small>
      </div>

      <div class="row">
        <button id="autoB" onclick="autoTog()">🚀 Start Backend with PC: Checking…</button>
        <button onclick="askNotif()">🔔 Enable Notifications</button>
      </div>
    </div>
  </div>

  <!-- 3. FLEET TAB -->
  <div id="tab-fleet" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>👥 Multi-PC Fleet Manager</span>
        <span id="fleetCount" class="badge badge-green">1 Active Node</span>
      </h2>
      <div class="row" style="margin-bottom:12px">
        <input id="fleetSearch" placeholder="🔍 Search fleet (by hostname, IP, or group)…" oninput="filterFleet()">
        <button onclick="fleetRefresh()" style="flex:0 0 100px">🔄 Refresh</button>
        <button class="acc" onclick="$('fleetAddBox').style.display=$('fleetAddBox').style.display==='none'?'block':'none'" style="flex:0 0 90px">➕ Add PC</button>
      </div>
      
      <div id="fleetAddBox" style="display:none;background:var(--surface-inset);padding:14px;border-radius:14px;margin-bottom:12px;border:1px solid var(--border-card)">
        <div style="font-weight:700;margin-bottom:10px">Register Remote Node</div>
        <input id="fAddName" placeholder="PC Name (e.g. Gaming PC, Office Laptop)" style="margin-bottom:8px">
        <input id="fAddUrl" placeholder="Node URL (e.g. http://192.168.1.50:8765 or Tailscale IP)" style="margin-bottom:8px">
        <div class="row">
          <button class="acc" onclick="addFleetNode()">Save Node</button>
          <button onclick="$('fleetAddBox').style.display='none'">Cancel</button>
        </div>
      </div>
      <div id="fleetList" style="display:flex;flex-direction:column;gap:8px;max-height:360px;overflow-y:auto"></div>
      <div class="row" style="margin-top:14px">
        <button onclick="autoAddDiscovered()">⚡ Auto-Register Discovered</button>
        <button class="red" onclick="broadcastFleet('lock')">🔒 Emergency Lock All</button>
        <button class="red" onclick="broadcastFleet('sleep')">🌙 Sleep All</button>
      </div>
    </div>
    <!-- Discovered LAN Devices -->
    <div class="card">
      <h2>
        <span>📡 Local Subnet Discovery</span>
        <button onclick="discover()" style="padding:4px 10px;font-size:12px">🔍 Scan Subnet</button>
      </h2>
      <div id="devList" class="stat" style="flex-direction:column;gap:6px">Scanning subnet for Project-X-Nano nodes…</div>
    </div>
  </div>

  <!-- 4. SCREEN & CAMERA TAB -->
  <div id="tab-screen" class="tab-content" style="display:none">
    <!-- Live Desktop Screen -->
    <div class="card">
      <h2>
        <span>🖥️ Live Desktop Screen</span>
        <span id="screenStatusBadge" class="badge badge-green" style="display:none">LIVE STREAM (30+ FPS)</span>
      </h2>
      <div class="row" style="margin-bottom:12px">
        <button id="liveB" class="acc" onclick="toggleScreenStream()">▶ Start Live Stream</button>
        <button onclick="shot()">📸 Single Snapshot</button>
        <button id="tapB" onclick="toggleTap()">🎯 Tap-to-Click: OFF</button>
        <button class="btn" onclick="toggleStreamFullscreen()">⛶ Immersive Fullscreen</button>
      </div>

      <!-- Container with Fullscreen capability -->
      <div id="screenContainer" class="screen-wrapper">
        <div class="screen-overlay-bar" id="streamOverlayBar" style="display:none">
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="toggleTap()" id="fsTapBtn">🎯 Tap: OFF</button>
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="shot()">📸 Snap</button>
          <button class="btn red" style="padding:4px 9px;font-size:11px" onclick="toggleStreamFullscreen()">✕ Exit Fullscreen</button>
        </div>
        <img id="shot" style="display:none;cursor:crosshair;box-shadow:0 6px 20px rgba(0,0,0,0.5)">
      </div>
    </div>

    <!-- Live Webcam Feed -->
    <div class="card">
      <h2>
        <span>📹 Remote Camera Feed</span>
        <span id="camStatusBadge" class="badge badge-green" style="display:none">CAMERA LIVE</span>
      </h2>
      <div class="row">
        <button id="camB" class="acc" onclick="toggleCamStream()">📹 Start Live Camera</button>
        <button onclick="camShot()">📷 Single Snapshot</button>
      </div>
      <img id="camimg" style="display:none;box-shadow:0 6px 20px rgba(0,0,0,0.5)" onerror="toast('⚠ Webcam stream unavailable')">
    </div>

    <!-- Audio & Speech Alerts -->
    <div class="card">
      <h2>🔊 Audio &amp; Room Alerts</h2>
      <div class="row">
        <button onclick="sound('beep')">🔔 Play Alert Chime</button>
        <button class="red" onclick="sound('alarm')">🚨 Find My PC Siren</button>
      </div>
      <div class="row">
        <input id="say" placeholder="Type text to make the PC speak out loud…">
        <button class="acc" onclick="speak()" style="flex:0 0 110px">🗣 Speak</button>
      </div>
    </div>
  </div>

  <!-- 5. CONTROLS TAB -->
  <div id="tab-controls" class="tab-content" style="display:none">
    <!-- THEME CUSTOMIZATION CARD IN REMOTE SECTION -->
    


    <!-- BI-DIRECTIONAL CLIPBOARD SYNC -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <h2 style="margin:0">📋 Bi-Directional Clipboard Sync</h2>
        <button class="btn acc" style="padding:4px 10px;font-size:11px" onclick="pullClipboard()">⬇ Read PC Clipboard</button>
      </div>
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 10px">
        Copy and paste text, code snippets, tokens, or URLs directly between your phone/laptop and the remote PC.
      </p>
      <textarea id="clipText" rows="3" placeholder="Type or paste text here to push to the remote PC clipboard…" style="width:100%;box-sizing:border-box;margin-bottom:10px;font-family:var(--font-mono);font-size:12px"></textarea>
      <div class="row" style="gap:8px">
        <button class="btn acc" style="flex:1" onclick="pushClipboard()">⬆ Push to PC Clipboard</button>
        <button class="btn" style="flex:1" onclick="copyLocalClip()">📄 Copy to Phone/Browser</button>
      </div>
    </div>

    <!-- MATRIX SCREEN LOCK CONTROLLER -->
    <div class="card" style="border:1px solid rgba(0,255,102,0.35);background:linear-gradient(135deg,rgba(0,10,3,0.8) 0%,rgba(0,40,15,0.3) 100%)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <h2 style="margin:0;color:#00ff66">⚡ Matrix Stealth Lock ("PROJECT X")</h2>
        <span id="matrixBadge" style="padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;background:rgba(100,116,139,0.3);color:var(--text-muted)">IDLE</span>
      </div>
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 14px">
        Turns the entire PC screen pitch black with an animated green digital rain Matrix theme and glowing <b>PROJECT X</b> text. Unclosable and blocks input on the physical PC.
      </p>
      <div class="row" style="gap:10px">
        <button id="btnMatrixStart" class="btn acc" style="flex:1;font-weight:700;background:linear-gradient(135deg,#059669,#10b981)" onclick="toggleMatrixLock(true)">
          🔒 Lock PC with Matrix Screen
        </button>
        <button id="btnMatrixStop" class="btn red" style="flex:1;font-weight:700;display:none" onclick="toggleMatrixLock(false)">
          🔓 Unlock / Dismiss Matrix Screen
        </button>
      </div>
      <div style="margin-top:10px;font-size:11px;color:var(--text-muted)">
        💡 <b>Host Keyboard Bypass:</b> Type <code>mexxz</code> on the physical keyboard to unlock immediately.
      </div>
    </div>

    <!-- FAKE WINDOWS UPDATE CONTROLLER -->
    <div class="card" style="border:1px solid rgba(59,130,246,0.35);background:linear-gradient(135deg,rgba(15,23,42,0.7) 0%,rgba(30,58,138,0.25) 100%)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <h2 style="margin:0">🛡️ Remote Anti-Tamper &amp; Fake Windows Update</h2>
        <span id="fakeUpdateBadge" style="padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;background:rgba(100,116,139,0.3);color:var(--text-muted)">IDLE</span>
      </div>
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 14px">
        Launches an authentic, animated full-screen Windows Update loading screen on the PC. Anyone in the room will think the PC is installing Windows updates and won't touch it.
      </p>
      <div class="row" style="gap:10px">
        <button id="btnFakeStart" class="btn acc" style="flex:1;font-weight:700;background:linear-gradient(135deg,#2563eb,#1d4ed8)" onclick="toggleFakeUpdate(true)">
          🚨 Launch Fake Update Screen
        </button>
        <button id="btnFakeStop" class="btn red" style="flex:1;font-weight:700;display:none" onclick="toggleFakeUpdate(false)">
          ⏹ Stop &amp; Dismiss Fake Screen
        </button>
      </div>
      <div style="margin-top:10px;font-size:11px;color:var(--text-muted)">
        💡 <b>Secret Host Bypass:</b> Typing <code>mexxz</code> on the physical keyboard of the PC will also immediately exit the fake update screen.
      </div>
    </div>

    <div class="card">
      <h2>🎨 Remote Dashboard Theme &amp; Styling</h2>
      <div class="row">
        <div style="flex:1">
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">Select Dashboard Theme:</label>
          <select id="themePickerRemote" onchange="setTheme(this.value)">
            <option value="cyber">⚡ Cyber Dark (Default Modern)</option>
            <option value="oled">🖤 OLED Pitch Black (High Contrast)</option>
            <option value="synthwave">🔮 Neon Synthwave (Magenta/Violet)</option>
            <option value="matrix">💻 Emerald Matrix (Hacker Green)</option>
            <option value="nord">❄ Arctic Nord (Glacial Blue)</option>
            <option value="crimson">🩸 Crimson Red (Stealth Blood)</option>
          </select>
        </div>
        <button onclick="toggleDashboardFullscreen()" style="margin-top:22px;flex:0 0 160px">
          ⛶ Fullscreen Mode
        </button>
      </div>
    </div>

    <!-- Touchpad Trackpad -->
    <div class="card">
      <h2>🖱️ Virtual Touchpad Trackpad</h2>
      <div style="display:flex;gap:12px">
        <div id="pad" style="flex:1;height:220px;background:var(--surface-inset);border:1px dashed var(--border-card-hover);border-radius:16px;touch-action:none;display:flex;align-items:center;justify-content:center;color:var(--text-muted);user-select:none;font-weight:600">
          Touch &amp; Drag to Move Cursor · Tap to Click
        </div>
        <div id="scroll" style="width:54px;height:220px;background:var(--surface-inset);border:1px dashed var(--border-card-hover);border-radius:16px;touch-action:none;display:flex;align-items:center;justify-content:center;color:var(--text-muted);user-select:none;font-size:20px">
          ↕
        </div>
      </div>
      <div class="grid" style="margin-top:12px">
        <button onclick="click_('left')">Left Click</button>
        <button onclick="click_('left',true)">Double Click</button>
        <button onclick="click_('right')">Right Click</button>
      </div>
    </div>

    <!-- Virtual Keyboard -->
    <div class="card">
      <h2>⌨️ Virtual Keyboard Remote</h2>
      <input id="typed" placeholder="Type text to send to PC…">
      <div class="row">
        <button onclick="typeText(false)">⌨ Type Text</button>
        <button class="acc" onclick="typeText(true)">Type + Enter</button>
      </div>
      <div class="grid" style="margin-top:12px">
        <button onclick="key('enter')">Enter</button>
        <button onclick="key('backspace')">⌫ Backspace</button>
        <button onclick="key('esc')">Esc</button>
        <button onclick="key('tab')">Tab</button>
        <button onclick="key('space')">Space</button>
        <button onclick="key('delete')">Delete</button>
        <button onclick="key('left')">← Left</button>
        <button onclick="key('up')">↑ Up</button>
        <button onclick="key('down')">↓ Down</button>
        <button onclick="key('right')" style="grid-column:2">→ Right</button>
        <button onclick="key('alt+tab')">Alt+Tab</button>
        <button onclick="key('win+d')">Desktop</button>
        <button onclick="key('alt+f4')">Alt+F4</button>
        <button onclick="key('ctrl+c')">Copy</button>
        <button onclick="key('ctrl+v')">Paste</button>
        <button onclick="key('ctrl+z')">Undo</button>
        <button onclick="key('f11')">Fullscreen</button>
        <button onclick="key('f5')">Refresh</button>
        <button onclick="key('ctrl+shift+esc')">Task Mgr</button>
      </div>
    </div>

    <!-- Sliders & Media -->
    <div class="card">
      <h2>🎚️ Master Hardware &amp; Media Sliders</h2>
      <div class="grid" style="margin-bottom:14px">
        <button onclick="media('prev')">⏮ Prev</button>
        <button onclick="media('play_pause')">⏯ Play/Pause</button>
        <button onclick="media('next')">⏭ Next</button>
        <button onclick="media('vol_down',3)">🔉 Volume −</button>
        <button onclick="media('mute')">🔇 Mute</button>
        <button onclick="media('vol_up',3)">🔊 Volume +</button>
      </div>
      <div style="margin-top:14px">
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted);margin-bottom:6px">
          <span>🔊 Master Volume</span><span id="volVal">50%</span>
        </div>
        <input id="vol" type="range" min="0" max="100" onchange="setVol(this.value);$('volVal').textContent=this.value+'%'">
      </div>
      <div style="margin-top:14px">
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted);margin-bottom:6px">
          <span>🔆 Monitor Brightness</span><span id="briVal">100%</span>
        </div>
        <input id="bri" type="range" min="0" max="100" onchange="setBri(this.value);$('briVal').textContent=this.value+'%'">
      </div>
    </div>

    <!-- Power Management -->
    <div class="card">
      <h2>⏻ Power &amp; Sleep Controls</h2>
      <div class="grid">
        <button class="red" onclick="pw('shutdown','Shut down')">⏻ Shut Down</button>
        <button class="red" onclick="pw('restart','Restart')">🔄 Restart</button>
        <button onclick="pw('sleep','Sleep')">🌙 Sleep</button>
        <button onclick="pw('hibernate','Hibernate')">💤 Hibernate</button>
        <button onclick="pw('lock','Lock')">🔒 Lock Screen</button>
        <button onclick="pw('logoff','Log off')">👤 Sign Out</button>
      </div>
      <div class="row" style="margin-top:12px;gap:8px">
        <button class="red" style="font-weight:700;flex:1" onclick="emergencyLockdown()">🚨 Emergency Lockdown</button>
        <button class="red" style="font-weight:700;flex:1;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4)" onclick="remoteUninstall()">🗑️ 1-Click Clean Uninstall</button>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="acc" style="flex:1" onclick="checkUpdate()">🔄 Check GitHub Updates</button>
      </div>
    </div>
  </div>


  <!-- 6. PROCESSES TAB -->
  <div id="tab-procs" class="tab-content" style="display:none">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
        <div>
          <h2 style="margin:0">⚡ Live Task &amp; Process Manager</h2>
          <span id="procSummary" style="font-size:12px;color:var(--text-muted)">Loading process metrics…</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);cursor:pointer">
            <input type="checkbox" id="autoProcRefresh" onchange="toggleAutoProcRefresh(this.checked)"> Auto-Refresh (3s)
          </label>
          <button class="btn acc" style="padding:6px 12px;font-size:12px" onclick="loadProcesses()">🔄 Refresh</button>
        </div>
      </div>

      <!-- Controls: Filter & Sort -->
      <div class="row" style="gap:10px;margin-bottom:14px">
        <input id="procSearch" placeholder="🔍 Search by process name or PID…" oninput="filterProcesses()" style="flex:2">
        <select id="procSort" onchange="loadProcesses()" style="flex:1">
          <option value="mem">Sort by Memory (Highest)</option>
          <option value="cpu">Sort by CPU (Highest)</option>
          <option value="name">Sort by Name (A-Z)</option>
        </select>
      </div>

      <!-- Process Table -->
      <div style="max-height:550px;overflow-y:auto;border:1px solid var(--border-card);border-radius:12px">
        <table style="width:100%;border-collapse:collapse;font-size:12px;text-align:left">
          <thead>
            <tr style="background:var(--surface-inset);color:var(--text-muted);border-bottom:1px solid var(--border-card)">
              <th style="padding:10px 14px">Name / PID</th>
              <th style="padding:10px 14px">CPU %</th>
              <th style="padding:10px 14px">Memory</th>
              <th style="padding:10px 14px">Status</th>
              <th style="padding:10px 14px;text-align:right">Actions</th>
            </tr>
          </thead>
          <tbody id="procTableBody">
            <!-- Dynamic Rows -->
          </tbody>
        </table>
      </div>
    </div>
  </div>



  <!-- 7. NETWORK PORTS TAB -->
  <div id="tab-ports" class="tab-content" style="display:none">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
        <div>
          <h2 style="margin:0">🌐 Active Listening Ports &amp; Sockets</h2>
          <span id="portsSummary" style="font-size:12px;color:var(--text-muted)">Scanning network bindings…</span>
        </div>
        <button class="btn acc" style="padding:6px 12px;font-size:12px" onclick="loadPorts()">🔄 Scan Ports</button>
      </div>

      <div class="row" style="gap:10px;margin-bottom:14px">
        <input id="portSearch" placeholder="🔍 Filter by port number or process name…" oninput="filterPorts()" style="flex:1">
      </div>

      <div style="max-height:550px;overflow-y:auto;border:1px solid var(--border-card);border-radius:12px">
        <table style="width:100%;border-collapse:collapse;font-size:12px;text-align:left">
          <thead>
            <tr style="background:var(--surface-inset);color:var(--text-muted);border-bottom:1px solid var(--border-card)">
              <th style="padding:10px 14px">Port</th>
              <th style="padding:10px 14px">Protocol</th>
              <th style="padding:10px 14px">Bind Address</th>
              <th style="padding:10px 14px">Process / PID</th>
              <th style="padding:10px 14px;text-align:right">Action</th>
            </tr>
          </thead>
          <tbody id="portsTableBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- 8. WINDOWS & LINUX SERVICES TAB -->
  <div id="tab-services" class="tab-content" style="display:none">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
        <div>
          <h2 style="margin:0">⚙️ Services &amp; Daemons Manager</h2>
          <span id="servicesSummary" style="font-size:12px;color:var(--text-muted)">Querying service manager…</span>
        </div>
        <button class="btn acc" style="padding:6px 12px;font-size:12px" onclick="loadServices()">🔄 Refresh Services</button>
      </div>

      <div class="row" style="gap:10px;margin-bottom:14px">
        <input id="serviceSearch" placeholder="🔍 Search service by name or identifier…" oninput="filterServices()" style="flex:1">
      </div>

      <div style="max-height:550px;overflow-y:auto;border:1px solid var(--border-card);border-radius:12px">
        <table style="width:100%;border-collapse:collapse;font-size:12px;text-align:left">
          <thead>
            <tr style="background:var(--surface-inset);color:var(--text-muted);border-bottom:1px solid var(--border-card)">
              <th style="padding:10px 14px">Display Name / Service</th>
              <th style="padding:10px 14px">Startup Type</th>
              <th style="padding:10px 14px">Status</th>
              <th style="padding:10px 14px;text-align:right">Controls</th>
            </tr>
          </thead>
          <tbody id="servicesTableBody"></tbody>
        </table>
      </div>
    </div>
  </div>


    <!-- 6. FILES & DRIVES TAB -->
  <div id="tab-files" class="tab-content" style="display:none">
    <div class="card">
      <h2><span>📁 Storage Drives &amp; File Manager</span></h2>
      <div id="drives" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px"></div>
      <div style="display:flex;justify-content:space-between;align-items:center;background:var(--surface-inset);border:1px solid var(--border-card);padding:10px 14px;border-radius:12px;margin-bottom:12px;font-family:var(--font-mono);font-size:12px">
        <span id="fpath" style="word-break:break-all">/</span>
        <label class="btn acc" style="padding:4px 10px;font-size:11px;cursor:pointer">
          ⬆ Upload File <input id="upf" type="file" multiple style="display:none" onchange="upload()">
        </label>
      </div>
      <div id="files" style="max-height:420px;overflow-y:auto;display:flex;flex-direction:column;gap:6px"></div>
    </div>
  </div>

  <!-- 8. SECURITY & AUDIT TAB -->
  <div id="tab-security" class="tab-content" style="display:none">
    <div class="card">
      <h2><span>🛡️ Security Hardening &amp; Defense in Depth</span></h2>

      <div class="stat-box" style="margin-bottom:16px">
        <div class="stat-header">
          <span>🔐 TOTP Two-Factor Authentication (2FA)</span>
          <span id="totpStatusBadge" class="badge badge-green">Checking...</span>
        </div>
        <p style="color:var(--text-muted);font-size:13px;margin:8px 0 12px">
          Require a 6-digit one-time code from Google Authenticator, Authy, or 1Password every time anyone attempts to log in.
        </p>
        <div id="totpSetupArea">
          <button class="acc" onclick="start2FAEnroll()">📱 Set Up Authenticator 2FA</button>
        </div>
        <div id="totpActiveArea" style="display:none">
          <button class="red" onclick="disable2FA()">Disable 2FA</button>
        </div>

        <div id="totpModal" style="display:none;margin-top:14px;background:var(--surface-inset);padding:16px;border-radius:14px;border:1px solid var(--border-card);text-align:center">
          <div style="font-weight:700;margin-bottom:8px">Scan QR Code in Authenticator App</div>
          <div id="totpQrContainer" style="margin:12px auto;display:inline-block;padding:8px;background:#fff;border-radius:8px"></div>
          <div style="font-family:var(--font-mono);font-size:12px;margin-bottom:12px;word-break:break-all;color:var(--text-muted)">
            Key: <span id="totpSecretText" style="color:var(--accent)"></span>
          </div>
          <div class="row" style="max-width:280px;margin:auto">
            <input id="totpConfirmCode" placeholder="Enter 6-digit Code" maxlength="6" style="text-align:center;font-size:16px;letter-spacing:4px">
            <button class="acc" onclick="confirm2FA()">Verify &amp; Enable</button>
          </div>
        </div>
      </div>

      <div class="stat-box" style="margin-bottom:16px">
        <div class="stat-header">
          <span>📱 Connected Devices &amp; Revocable Sessions</span>
          <button class="btn" style="padding:2px 8px;font-size:11px" onclick="loadDevices()">🔄 Refresh</button>
        </div>
        <p style="color:var(--text-muted);font-size:13px;margin:6px 0 10px">
          JWT session tokens expire after 1 hour. Revoke untrusted or lost devices immediately.
        </p>
        <div id="deviceList" style="display:flex;flex-direction:column;gap:8px;max-height:220px;overflow-y:auto"></div>
      </div>

      <div class="stat-box" style="margin-bottom:16px">
        <div class="stat-header">
          <span>📜 Comprehensive Audit Trail (IP, ASN &amp; Timestamps)</span>
          <button class="btn" style="padding:2px 8px;font-size:11px" onclick="loadAuditLogs()">🔄 Refresh</button>
        </div>
        <p style="color:var(--text-muted);font-size:13px;margin:6px 0 10px">
          Every remote command, login attempt, file operation, and service manipulation is permanently audited.
        </p>
        <div id="auditLogList" style="max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;font-family:var(--font-mono);font-size:11px"></div>
      </div>

      <div class="stat-box" style="border:1px solid rgba(239,68,68,0.4);background:rgba(239,68,68,0.05)">
        <div class="stat-header"><span style="color:var(--red)">💥 Emergency Panic Wipe (--nuke)</span></div>
        <p style="color:var(--text-muted);font-size:13px;margin:8px 0 12px">
          Tears down all tunnels immediately, drops Windows Firewall exceptions, zeroes and deletes credentials, stops watchdog, and terminates this server agent.
        </p>
        <button class="red" style="font-weight:700" onclick="triggerPanicNuke()">🔥 Emergency Panic Wipe PC Credentials</button>
      </div>
    </div>
  </div>
  <!-- 7. TERMINAL TAB -->
  <div id="tab-terminal" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>💻 Remote Terminal Console</span>
        <span id="adminB" class="badge badge-green">USER CONSOLE</span>
      </h2>
      <div id="termLocked" style="display:none;background:var(--surface-inset);padding:16px;border-radius:14px;border:1px solid var(--border-card);text-align:center">
        <div style="font-weight:700;margin-bottom:6px">🔒 Terminal Protected</div>
        <p style="color:var(--text-muted);font-size:13px;margin:0 0 12px">Re-enter master password to authorize administrative shell:</p>
        <div class="row" style="max-width:320px;margin:auto">
          <input id="tpw" type="password" placeholder="Master Password">
          <button class="acc" onclick="termUnlock()" style="flex:0 0 90px">Unlock</button>
        </div>
      </div>
      
      <div id="termOn" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--text-muted);margin-bottom:8px">
          <span>Working Dir: <b id="tcwd" style="font-family:var(--font-mono);color:var(--text-main)">...</b></span>
          <div style="display:flex;gap:8px;align-items:center">
            <select id="tshell" class="pill-select" style="padding:3px 8px;font-size:11px"></select>
            <button class="red" style="padding:3px 8px;font-size:11px" onclick="termLock()">Lock</button>
          </div>
        </div>
        <pre id="tout" style="background:#05070d;color:#38bdf8;font-family:var(--font-mono);font-size:12px;padding:12px;border-radius:12px;height:280px;overflow-y:auto;white-space:pre-wrap;border:1px solid var(--border-card)"></pre>
        <div class="row">
          <input id="tcmd" placeholder="Enter shell command (e.g. dir, ping google.com, netstat)..." style="font-family:var(--font-mono)">
          <button class="acc" onclick="termRun()" style="flex:0 0 90px">Run</button>
        </div>
      </div>

      <div id="termOff" style="display:none;color:var(--red);padding:10px">
        Terminal is disabled in config.json.
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>

<!-- ==========================================================================
     CLIENT SCRIPTS: AUTH, WEBSOCKET / HTTP, HARDWARE & THEMES
     ========================================================================== -->
<script>
const $ = id => document.getElementById(id);
const toast = msg => {
  const t = $('toast');
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.style.display = 'none', 3500);
};

/* ================= THEME ENGINE ================= */
function setTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  localStorage.setItem('pxn_theme', name);
  if ($('themePickerHeader')) $('themePickerHeader').value = name;
  if ($('themePickerRemote')) $('themePickerRemote').value = name;
}
// Init theme from storage
const savedTheme = localStorage.getItem('pxn_theme') || 'cyber';
setTheme(savedTheme);

/* ================= FULLSCREEN HELPERS ================= */
function toggleDashboardFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().then(() => {
      $('fsIcon').textContent = '✕';
    }).catch(() => toast('Fullscreen mode not permitted'));
  } else {
    document.exitFullscreen().then(() => {
      $('fsIcon').textContent = '⛶';
    });
  }
}
document.addEventListener('fullscreenchange', () => {
  const isFs = !!document.fullscreenElement;
  $('fsIcon').textContent = isFs ? '✕' : '⛶';
  const overlay = $('streamOverlayBar');
  if (overlay) overlay.style.display = (isFs && document.fullscreenElement === $('screenContainer')) ? 'flex' : 'none';
});

function toggleStreamFullscreen() {
  const container = $('screenContainer');
  if (!document.fullscreenElement) {
    container.requestFullscreen().then(() => {
      $('streamOverlayBar').style.display = 'flex';
      toast('Press ESC or tap ✕ to exit fullscreen');
    }).catch(() => toast('Stream fullscreen not permitted'));
  } else {
    document.exitFullscreen();
  }
}

/* ================= API CALL WRAPPER ================= */
async function api(path, body = null, method = 'POST') {
  const headers = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('pxn_jwt_token');
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opt = { method: body ? method : 'GET', headers };
  if (body) opt.body = JSON.stringify(body);
  try {
    const res = await fetch('/api/' + path, opt);
    if (res.status === 401) {
      localStorage.removeItem('pxn_jwt_token');
      show(false);
      return { error: 'Unauthorized' };
    }
    setHostConnectionStatus(true);
    return await res.json();
  } catch (err) {
    setHostConnectionStatus(false);
    throw err;
  }
}

/* ================= CONNECTION MONITOR & RECONNECT ================= */
let isServerOnline = true;
function setHostConnectionStatus(online) {
  if (isServerOnline === online) return;
  isServerOnline = online;
  const banner = $('reconnectBanner');
  if (!online) {
    banner.style.display = 'block';
  } else {
    banner.style.display = 'none';
  }
}

/* Heartbeat check */
setInterval(async () => {
  if ($('main').style.display !== 'none') {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) {
        setHostConnectionStatus(true);
      } else if (res.status === 401) {
        attemptAutoConnect();
      }
    } catch (e) {
      setHostConnectionStatus(false);
    }
  }
}, 4000);

/* ================= AUTH & AUTO-CONNECT ================= */
function show(ok) {
  $('login').style.display = ok ? 'none' : 'block';
  $('main').style.display = ok ? 'block' : 'none';
  if (ok) {
    init();
    updateHostServerPills();
  }
}

let gDeviceId = localStorage.getItem('pxn_device_id') || ('dev_' + Math.random().toString(36).substring(2, 10));
localStorage.setItem('pxn_device_id', gDeviceId);
let gPendingLoginPw = '';
let gPendingTotpSecret = '';

async function login() {
  const pwInput = $('pw');
  const totpInput = $('loginTotp');
  const remember = $('chkRemember') ? $('chkRemember').checked : true;

  let pw = pwInput ? pwInput.value : '';
  if (!pw && gPendingLoginPw) {
    pw = gPendingLoginPw;
  }
  if (!pw && remember) {
    pw = localStorage.getItem('pxn_saved_pw') || '';
  }

  if (!pw) {
    toast('⚠️ Please enter Master Password');
    if (pwInput) pwInput.focus();
    return;
  }

  const totpCode = totpInput ? totpInput.value.trim() : '';

  try {
    const d = await api('login', {
      password: pw,
      totp_code: totpCode,
      remember: remember,
      device_id: gDeviceId,
      device_name: navigator.userAgent.includes('Mobile') ? 'Mobile Device' : 'Desktop Browser'
    });

    if (d.totp_required) {
      gPendingLoginPw = pw;
      if ($('login2faBox')) {
        $('login2faBox').style.display = 'block';
      }
      if (totpInput) {
        totpInput.focus();
      }
      toast('🔐 2FA Code Required - Enter 6-digit code');
      return;
    }

    if (d.ok) {
      if (remember) {
        localStorage.setItem('pxn_remember', 'true');
        localStorage.setItem('pxn_saved_pw', pw);
      } else {
        localStorage.removeItem('pxn_remember');
        localStorage.removeItem('pxn_saved_pw');
      }

      if (d.token) {
        localStorage.setItem('pxn_jwt_token', d.token);
      }

      gPendingLoginPw = '';
      if (pwInput) pwInput.value = '';
      if (totpInput) totpInput.value = '';
      if ($('login2faBox')) $('login2faBox').style.display = 'none';
      show(true);
      toast('⚡ Connected to Host PC');
      check2FAStatus();
    } else {
      toast('❌ ' + (d.error || 'Authentication Failed'));
      if (totpInput && $('login2faBox') && $('login2faBox').style.display !== 'none') {
        totpInput.select();
        totpInput.focus();
      }
    }
  } catch (e) {
    toast('❌ Connection failed');
  }
}

async function attemptAutoConnect() {
  const remember = localStorage.getItem('pxn_remember') !== 'false';
  const savedToken = localStorage.getItem('pxn_jwt_token');

  if (savedToken) {
    try {
      const d = await api('stats');
      if (!d.error) {
        show(true);
        toast('⚡ Session restored');
        return;
      }
    } catch(e) {}
  }

  if (remember) {
    const savedPw = localStorage.getItem('pxn_saved_pw');
    if (savedPw && $('pw') && !$('pw').value) {
      $('pw').value = savedPw;
    }
  }
}

async function logout() {
  localStorage.removeItem('pxn_jwt_token');
  await api('logout', {});
  show(false);
}

/* ================= 2FA TOTP MANAGEMENT ================= */
async function check2FAStatus() {
  try {
    const d = await api('2fa/status');
    const badge = $('totpStatusBadge');
    if (badge) {
      badge.textContent = d.enabled ? 'ACTIVE & ENFORCED' : 'DISABLED';
      badge.className = 'badge ' + (d.enabled ? 'badge-green' : 'badge-yellow');
    }
    if ($('totpSetupArea')) $('totpSetupArea').style.display = d.enabled ? 'none' : 'block';
    if ($('totpActiveArea')) $('totpActiveArea').style.display = d.enabled ? 'block' : 'none';
  } catch(e) {}
}

async function start2FAEnroll() {
  const d = await api('2fa/enroll');
  if (d.ok) {
    gPendingTotpSecret = d.secret;
    $('totpQrContainer').innerHTML = `<img src="data:image/png;base64,${d.qr_b64}" style="width:160px;height:160px;display:block">`;
    $('totpSecretText').textContent = d.secret;
    $('totpModal').style.display = 'block';
    if ($('totpConfirmCode')) {
      $('totpConfirmCode').value = '';
      $('totpConfirmCode').focus();
    }
  } else {
    toast('❌ ' + (d.error || 'Failed to start 2FA enrollment'));
  }
}

async function confirm2FA() {
  const code = $('totpConfirmCode').value.trim();
  if (!code) return toast('Please enter the 6-digit code');
  const d = await api('2fa/confirm', { code: code, secret: gPendingTotpSecret });
  if (d.ok) {
    toast('✅ 2FA successfully activated!');
    $('totpModal').style.display = 'none';
    gPendingTotpSecret = '';
    check2FAStatus();
  } else {
    toast('❌ ' + (d.error || 'Verification failed'));
  }
}

async function disable2FA() {
  const pw = prompt('Enter Master Password to disable 2FA:');
  if (!pw) return;
  const d = await api('2fa/disable', { password: pw });
  if (d.ok) {
    toast('2FA Disabled');
    check2FAStatus();
  } else {
    toast('❌ ' + (d.error || 'Failed'));
  }
}
    toast('❌ ' + (d.error || 'Failed'));
  }
}

/* ================= DEVICES & SESSIONS ================= */
async function loadDevices() {
  const d = await api('devices');
  const list = $('deviceList');
  if (!list) return;
  if (!d.devices || !d.devices.length) {
    list.innerHTML = '<span style="color:var(--text-muted)">No registered devices.</span>';
    return;
  }
  list.innerHTML = d.devices.map(dev => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--surface-inset);border-radius:10px;border:1px solid var(--border-card)">
      <div>
        <div style="font-weight:700;font-size:12px">${dev.name} ${dev.id === gDeviceId ? '<span style="color:var(--accent)">(This Device)</span>' : ''}</div>
        <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">IP: ${dev.last_ip || 'N/A'} | Last: ${dev.last_active || 'N/A'}</div>
      </div>
      <div>
        ${dev.revoked ? '<span class="badge badge-yellow">REVOKED</span>' : `<button class="red" style="padding:3px 8px;font-size:11px" onclick="revokeDevice('${dev.id}')">Revoke</button>`}
      </div>
    </div>
  `).join('');
}

async function revokeDevice(id) {
  if (!confirm('Revoke access for this device? It will be disconnected.')) return;
  const d = await api('devices/revoke', { device_id: id });
  toast(d.msg || d.error);
  loadDevices();
}

/* ================= AUDIT LOGS ================= */
async function loadAuditLogs() {
  const d = await api('audit/logs');
  const list = $('auditLogList');
  if (!list) return;
  if (!d.logs || !d.logs.length) {
    list.innerHTML = '<span style="color:var(--text-muted)">No audit records yet.</span>';
    return;
  }
  list.innerHTML = d.logs.map(log => `
    <div style="padding:6px 10px;background:var(--surface-inset);border-radius:8px;border:1px solid var(--border-card)">
      <span style="color:var(--accent)">[${log.timestamp || 'RECENT'}]</span>
      <span style="color:#a855f7">[${log.ip || 'LAN'} - ${log.asn || 'LOCAL'}]</span>
      <span style="color:var(--text-main)">${typeof log.action === 'string' ? log.action : JSON.stringify(log.action)}</span>
    </div>
  `).join('');
}

/* ================= PANIC WIPE ================= */
async function triggerPanicNuke() {
  const pw = prompt('⚠️ EMERGENCY PANIC WIPE: All tunnels dropped, credentials securely wiped, agent killed. Type master password to confirm:');
  if (!pw) return;
  try {
    const d = await api('panic/nuke', { password: pw });
    alert(d.msg || 'PANIC WIPE ENGAGED');
    location.reload();
  } catch(e) {
    alert('Panic wipe signal dispatched.');
    location.reload();
  }
}


function updateHostServerPills() {
  const hostIp = location.hostname;
  const port = location.port || '8765';
  $('srvLanUrl').textContent = `http://${hostIp}:${port}`;
  // Check Cloudflare tunnel URL if any
  fetch('/api/tunnel/url').then(r => r.json()).then(d => {
    if (d.public_url) {
      $('srvTunnelUrl').textContent = d.public_url;
    }
  }).catch(()=>{});
}

function copyText(str) {
  navigator.clipboard ? navigator.clipboard.writeText(str).then(() => toast('✓ Copied: ' + str)) : prompt('Copy URL:', str);
}

/* ================= TAB NAVIGATION ================= */



/* ================= CODER TOOLS & DIAGNOSTICS ================= */

// 1. Bi-directional Clipboard
async function pullClipboard() {
  toast("Reading remote PC clipboard…");
  try {
    const res = await api('clipboard');
    if (res.ok) {
      $('clipText').value = res.text || '';
      toast("✓ Remote clipboard loaded");
    } else {
      toast("⚠ " + (res.error || "Failed to read clipboard"));
    }
  } catch(e) { toast("⚠ Error loading clipboard"); }
}

async function pushClipboard() {
  const text = $('clipText').value;
  try {
    const res = await api('clipboard', { text: text }, 'POST');
    if (res.ok) toast("✓ PC Clipboard updated!");
    else toast("⚠ " + (res.error || "Failed to push clipboard"));
  } catch(e) { toast("⚠ Error setting clipboard"); }
}

function copyLocalClip() {
  const text = $('clipText').value;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => toast("✓ Copied to phone/browser!")).catch(() => toast("Copy failed"));
}

// 2. Active Network Ports
let rawPorts = [];
async function loadPorts() {
  $('portsSummary').textContent = "Scanning active listening ports…";
  try {
    const res = await api('network/ports');
    if (res.ok && res.ports) {
      rawPorts = res.ports;
      $('portsSummary').textContent = `${res.total} Active Listening Ports`;
      renderPorts(rawPorts);
    }
  } catch(e) { $('portsSummary').textContent = "Error scanning ports"; }
}

function filterPorts() {
  const q = ($('portSearch').value || '').toLowerCase().trim();
  if (!q) { renderPorts(rawPorts); return; }
  const filtered = rawPorts.filter(p => 
    String(p.port).includes(q) || (p.process || '').toLowerCase().includes(q) || (p.bind || '').includes(q)
  );
  renderPorts(filtered);
}

function renderPorts(list) {
  const tbody = $('portsTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-muted)">No matching ports found</td></tr>';
    return;
  }
  list.forEach(p => {
    const tr = document.createElement('tr');
    tr.style.borderBottom = '1px solid var(--border-card)';
    tr.innerHTML = `
      <td style="padding:10px 14px">
        <span style="font-family:var(--font-mono);font-weight:700;color:var(--accent-cyan);font-size:13px">:${p.port}</span>
      </td>
      <td style="padding:10px 14px">
        <span style="padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;background:rgba(59,130,246,0.15);color:#60a5fa">${p.proto}</span>
      </td>
      <td style="padding:10px 14px;font-family:var(--font-mono);color:var(--text-muted)">${p.bind}</td>
      <td style="padding:10px 14px">
        <div style="font-weight:600">${p.process}</div>
        <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">PID: ${p.pid || 'N/A'}</div>
      </td>
      <td style="padding:10px 14px;text-align:right">
        ${p.pid && p.pid > 4 ? `<button class="btn red" style="padding:4px 8px;font-size:11px" onclick="killPort(${p.port}, ${p.pid})">Free Port</button>` : '<span style="color:var(--text-muted);font-size:11px">System</span>'}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function killPort(port, pid) {
  if (!confirm(`Free port :${port} by terminating PID ${pid}?`)) return;
  const res = await api('network/kill_port', { port: port, pid: pid }, 'POST');
  if (res.ok) {
    toast("✓ " + res.msg);
    loadPorts();
  } else {
    toast("⚠ " + (res.error || "Failed to free port"));
  }
}

// 3. Services Manager
let rawServices = [];
async function loadServices() {
  $('servicesSummary').textContent = "Querying services…";
  try {
    const res = await api('services');
    if (res.ok && res.services) {
      rawServices = res.services;
      $('servicesSummary').textContent = `${res.total} Services Registered`;
      renderServices(rawServices);
    }
  } catch(e) { $('servicesSummary').textContent = "Error loading services"; }
}

function filterServices() {
  const q = ($('serviceSearch').value || '').toLowerCase().trim();
  if (!q) { renderServices(rawServices); return; }
  const filtered = rawServices.filter(s => 
    s.display.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
  );
  renderServices(filtered);
}

function renderServices(list) {
  const tbody = $('servicesTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--text-muted)">No matching services found</td></tr>';
    return;
  }
  list.forEach(s => {
    const isRunning = s.status === 'Running';
    const statusColor = isRunning ? '#10b981' : '#64748b';
    const tr = document.createElement('tr');
    tr.style.borderBottom = '1px solid var(--border-card)';
    tr.innerHTML = `
      <td style="padding:10px 14px">
        <div style="font-weight:600">${s.display}</div>
        <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">${s.name}</div>
      </td>
      <td style="padding:10px 14px;color:var(--text-muted)">${s.startup}</td>
      <td style="padding:10px 14px">
        <span style="padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700;background:${statusColor}22;color:${statusColor}">${s.status.toUpperCase()}</span>
      </td>
      <td style="padding:10px 14px;text-align:right">
        <div style="display:flex;gap:6px;justify-content:flex-end">
          ${isRunning ? 
            `<button class="btn red" style="padding:4px 8px;font-size:11px" onclick="serviceAction('${s.name}', 'stop')">Stop</button>
             <button class="btn" style="padding:4px 8px;font-size:11px" onclick="serviceAction('${s.name}', 'restart')">Restart</button>` :
            `<button class="btn acc" style="padding:4px 8px;font-size:11px" onclick="serviceAction('${s.name}', 'start')">Start</button>`
          }
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function serviceAction(name, action) {
  toast(`${action.toUpperCase()} service: ${name}…`);
  const res = await api('services/action', { name: name, action: action }, 'POST');
  if (res.ok) {
    toast("✓ " + res.msg);
    setTimeout(loadServices, 1200);
  } else {
    toast("⚠ " + (res.error || "Action failed"));
  }
}

// 4. Per-Core Hardware Telemetry
async function updateHardwareTelemetry() {
  try {
    const res = await api('hardware/telemetry');
    if (res.ok) {
      if ($('hwFreq') && res.cpu_freq) {
        $('hwFreq').textContent = `${res.cpu_freq} MHz · ${res.cores.length} Cores`;
      }
      const container = $('coreBars');
      if (container && res.cores) {
        container.innerHTML = '';
        res.cores.forEach((load, idx) => {
          const barColor = load > 80 ? '#ef4444' : (load > 40 ? '#f59e0b' : '#10b981');
          const box = document.createElement('div');
          box.style.background = 'var(--surface-inset)';
          box.style.border = '1px solid var(--border-card)';
          box.style.borderRadius = '8px';
          box.style.padding = '6px';
          box.style.textAlign = 'center';
          box.innerHTML = `
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">C${idx}</div>
            <div style="height:32px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden;position:relative">
              <div style="position:absolute;bottom:0;left:0;right:0;height:${load}%;background:${barColor};transition:height 0.4s ease"></div>
            </div>
            <div style="font-size:10px;font-family:var(--font-mono);font-weight:700;margin-top:4px">${Math.round(load)}%</div>
          `;
          container.appendChild(box);
        });
      }
    }
  } catch(e) {}
}

/* ================= MATRIX SCREEN LOCK ================= */
async function checkMatrixStatus() {
  try {
    const d = await api('matrix_screen/status');
    const badge = $('matrixBadge');
    const bStart = $('btnMatrixStart');
    const bStop = $('btnMatrixStop');
    if (!badge) return;
    if (d.active) {
      badge.textContent = '🟢 ACTIVE ON PC';
      badge.style.background = 'rgba(0,255,102,0.2)';
      badge.style.color = '#00ff66';
      if (bStart) bStart.style.display = 'none';
      if (bStop) bStop.style.display = 'block';
    } else {
      badge.textContent = 'IDLE';
      badge.style.background = 'rgba(100,116,139,0.3)';
      badge.style.color = 'var(--text-muted)';
      if (bStart) bStart.style.display = 'block';
      if (bStop) bStop.style.display = 'none';
    }
  } catch (e) {}
}

async function toggleMatrixLock(start) {
  if (start) {
    if (!confirm('Lock Host PC with Matrix "PROJECT X" Screen?\n\nThe PC monitor will turn black with animated green code and glowing PROJECT X text.')) return;
    toast('Activating Matrix Screen Lock on PC...');
    const r = await api('matrix_screen/start', {}, 'POST');
    if (r.ok) toast('✓ ' + r.msg);
  } else {
    toast('Dismissing Matrix Screen Lock...');
    const r = await api('matrix_screen/stop', {}, 'POST');
    if (r.ok) toast('✓ ' + r.msg);
  }
  checkMatrixStatus();
}

/* ================= FAKE WINDOWS UPDATE ================= */
async function checkFakeUpdateStatus() {
  try {
    const d = await api('fake_update/status');
    const badge = $('fakeUpdateBadge');
    const bStart = $('btnFakeStart');
    const bStop = $('btnFakeStop');
    if (!badge) return;
    if (d.active) {
      badge.textContent = '🟢 ACTIVE ON PC';
      badge.style.background = 'rgba(34,197,94,0.2)';
      badge.style.color = '#4ade80';
      if (bStart) bStart.style.display = 'none';
      if (bStop) bStop.style.display = 'block';
    } else {
      badge.textContent = 'IDLE';
      badge.style.background = 'rgba(100,116,139,0.3)';
      badge.style.color = 'var(--text-muted)';
      if (bStart) bStart.style.display = 'block';
      if (bStop) bStop.style.display = 'none';
    }
  } catch (e) {}
}

async function toggleFakeUpdate(start) {
  if (start) {
    if (!confirm('Launch full-screen Fake Windows Update screen on Host PC?\n\nThe PC will display an animated Windows Update screen to deter anyone from using it.')) return;
    toast('Launching Fake Update screen on PC...');
    const r = await api('fake_update/start', {}, 'POST');
    if (r.ok) toast('✓ ' + r.msg);
  } else {
    toast('Stopping Fake Update screen...');
    const r = await api('fake_update/stop', {}, 'POST');
    if (r.ok) toast('✓ ' + r.msg);
  }
  checkFakeUpdateStatus();
}

/* ================= LIVE PROCESS MANAGER ================= */
let rawProcesses = [];
let procRefreshTimer = null;

async function loadProcesses() {
  const sort = $('procSort') ? $('procSort').value : 'mem';
  try {
    const res = await api('processes?sort=' + sort);
    if (res.ok && res.processes) {
      rawProcesses = res.processes;
      $('procSummary').textContent = `${res.total} Active Processes · Showing top ${res.processes.length}`;
      renderProcesses(rawProcesses);
    }
  } catch (e) {
    $('procSummary').textContent = 'Error loading processes';
  }
}

function filterProcesses() {
  const q = ($('procSearch').value || '').toLowerCase().trim();
  if (!q) {
    renderProcesses(rawProcesses);
    return;
  }
  const filtered = rawProcesses.filter(p => 
    p.name.toLowerCase().includes(q) || String(p.pid).includes(q)
  );
  renderProcesses(filtered);
}

function renderProcesses(list) {
  const tbody = $('procTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-muted)">No matching processes found</td></tr>';
    return;
  }

  list.forEach(p => {
    const tr = document.createElement('tr');
    tr.style.borderBottom = '1px solid var(--border-card)';
    
    // Status styling
    const isSuspended = (p.status || '').toLowerCase().includes('suspend') || (p.status || '').toLowerCase().includes('stopped');
    const statusColor = isSuspended ? '#f59e0b' : '#10b981';

    tr.innerHTML = `
      <td style="padding:10px 14px">
        <div style="font-weight:600;color:var(--text-primary)">${p.name}</div>
        <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">PID: ${p.pid}</div>
      </td>
      <td style="padding:10px 14px">
        <span style="font-family:var(--font-mono);font-weight:600;color:${p.cpu > 15 ? '#ef4444' : 'var(--text-primary)'}">${p.cpu}%</span>
      </td>
      <td style="padding:10px 14px">
        <span style="font-family:var(--font-mono)">${p.mem_mb} MB</span>
      </td>
      <td style="padding:10px 14px">
        <span style="padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700;background:${statusColor}22;color:${statusColor}">${p.status.toUpperCase()}</span>
      </td>
      <td style="padding:10px 14px;text-align:right">
        <div style="display:flex;gap:6px;justify-content:flex-end">
          ${isSuspended ? 
            `<button class="btn" style="padding:4px 8px;font-size:11px;color:#10b981" title="Resume Process" onclick="resumeProcess(${p.pid}, '${p.name}')">▶</button>` : 
            `<button class="btn" style="padding:4px 8px;font-size:11px;color:#f59e0b" title="Pause / Suspend Process" onclick="suspendProcess(${p.pid}, '${p.name}')">⏸</button>`
          }
          <button class="btn red" style="padding:4px 8px;font-size:11px" title="Terminate Process" onclick="killProcess(${p.pid}, '${p.name}')">❌</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function killProcess(pid, name) {
  if (!confirm(`Are you sure you want to terminate:\n${name} (PID: ${pid})?`)) return;
  const res = await api('processes/kill', { pid: pid }, 'POST');
  if (res.ok) {
    toast('✓ ' + (res.msg || 'Process killed'));
    loadProcesses();
  } else {
    toast('⚠ ' + (res.error || 'Failed to kill process'));
  }
}

async function suspendProcess(pid, name) {
  const res = await api('processes/suspend', { pid: pid }, 'POST');
  if (res.ok) {
    toast('✓ ' + res.msg);
    loadProcesses();
  } else {
    toast('⚠ ' + (res.error || 'Could not suspend'));
  }
}

async function resumeProcess(pid, name) {
  const res = await api('processes/resume', { pid: pid }, 'POST');
  if (res.ok) {
    toast('✓ ' + res.msg);
    loadProcesses();
  } else {
    toast('⚠ ' + (res.error || 'Could not resume'));
  }
}

function toggleAutoProcRefresh(enabled) {
  if (procRefreshTimer) {
    clearInterval(procRefreshTimer);
    procRefreshTimer = null;
  }
  if (enabled) {
    procRefreshTimer = setInterval(loadProcesses, 3000);
  }
}

function showTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  const target = $('tab-' + name);
  if (target) target.style.display = 'block';
  if (name === 'procs') loadProcesses();
  if (name === 'controls') { checkFakeUpdateStatus(); checkMatrixStatus(); pullClipboard(); }
  if (name === 'ports') loadPorts();
  if (name === 'services') loadServices();
  if (name === 'overview') updateHardwareTelemetry();
  if (name === 'procs') loadProcesses();
  if (name === 'controls') { checkFakeUpdateStatus(); checkMatrixStatus(); pullClipboard(); }
  if (name === 'ports') loadPorts();
  if (name === 'services') loadServices();
  if (name === 'overview') updateHardwareTelemetry();
  if (name === 'security') { check2FAStatus(); loadDevices(); loadAuditLogs(); }
  if (btn) btn.classList.add('active');
}

/* ================= OVERVIEW METRICS ================= */
async function stats() {
  try {
    const d = await api('stats');
    if (d.error) return;
    $('cpu').style.width = d.cpu + '%';
    $('cpuT').textContent = d.cpu + '%';
    $('ram').style.width = d.ram + '%';
    $('ramT').textContent = d.ram + '%';
    $('disk').style.width = d.disk + '%';
    $('diskT').textContent = d.disk + '%';
    $('osT').textContent = `${d.host} (${d.os}) · Uptime: ${d.uptime_min}m`;
    $('batT').textContent = d.battery ? `🔋 ${d.battery.percent}% ${d.battery.plugged ? '⚡' : ''}` : '⚡ AC Powered';
  } catch (e) {}
}

/* Quick commands & apps */
async function cmds() {
  try {
    const c = await api('commands');
    $('cmds').innerHTML = '';
    c.forEach(n => {
      const b = document.createElement('button');
      b.textContent = n;
      b.onclick = () => runCmd(n);
      $('cmds').appendChild(b);
    });
  } catch (e) {}
}
async function runCmd(n) {
  if (!confirm(`Execute "${n}" on Host PC?`)) return;
  $('cmdout').textContent = 'Executing command...';
  const d = await api('command', { name: n });
  $('cmdout').textContent = d.output || d.error || '';
}

function openUrl() {
  const u = $('url').value.trim();
  if (u) api('open_url', { url: u }).then(() => { $('url').value = ''; toast('🌐 Opened link on PC'); });
}
function sendMsg() {
  const m = $('msg').value.trim();
  if (m) api('message', { message: m }).then(() => { $('msg').value = ''; toast('💬 Message sent to PC screen'); });
}

/* ================= SCREEN STREAM (30+ FPS) & TAP-TO-CLICK ================= */
let screenStreaming = false;
let tapOn = false;

function toggleScreenStream() {
  screenStreaming = !screenStreaming;
  const img = $('shot');
  const btn = $('liveB');
  const badge = $('screenStatusBadge');

  if (screenStreaming) {
    img.src = '/api/stream/screen?t=' + Date.now();
    img.style.display = 'block';
    btn.textContent = '⏹ Stop Stream';
    btn.classList.add('red');
    btn.classList.remove('acc');
    badge.style.display = 'inline-block';
  } else {
    img.src = '';
    btn.textContent = '▶ Start Live Stream';
    btn.classList.remove('red');
    btn.classList.add('acc');
    badge.style.display = 'none';
  }
}

function shot() {
  const img = $('shot');
  img.src = '/api/screenshot?t=' + Date.now();
  img.style.display = 'block';
}

function toggleTap() {
  tapOn = !tapOn;
  const label = '🎯 Tap-to-Click: ' + (tapOn ? 'ON' : 'OFF');
  $('tapB').textContent = label;
  $('tapB').classList.toggle('acc', tapOn);
  if ($('fsTapBtn')) $('fsTapBtn').textContent = label;
}

$('shot').addEventListener('click', e => {
  if (!tapOn) return;
  const r = e.target.getBoundingClientRect();
  const fx = (e.clientX - r.left) / r.width;
  const fy = (e.clientY - r.top) / r.height;
  api('mouse/click_at', { x: fx, y: fy, right: e.ctrlKey || e.button === 2 });
  if (!screenStreaming) setTimeout(shot, 600);
});

/* Webcam */
let camStreaming = false;
function toggleCamStream() {
  camStreaming = !camStreaming;
  const img = $('camimg');
  const btn = $('camB');
  const badge = $('camStatusBadge');
  if (camStreaming) {
    img.src = '/api/stream/webcam?t=' + Date.now();
    img.style.display = 'block';
    btn.textContent = '⏹ Stop Camera';
    btn.classList.add('red');
    btn.classList.remove('acc');
    badge.style.display = 'inline-block';
  } else {
    img.src = '';
    btn.textContent = '📹 Start Live Camera';
    btn.classList.remove('red');
    btn.classList.add('acc');
    badge.style.display = 'none';
  }
}
function camShot() {
  const img = $('camimg');
  img.src = '/api/webcam?t=' + Date.now();
  img.style.display = 'block';
}

/* Audio & Speak */
function sound(k) { api('sound', { kind: k }); }
function speak() {
  const t = $('say').value.trim();
  if (t) api('speak', { text: t }).then(() => { $('say').value = ''; toast('🗣 Speaking on PC'); });
}

/* ================= REMOTE INPUTS (TOUCHPAD & KEYS) ================= */
function click_(b, d) { api('mouse/click', { button: b, double: !!d }); }
function key(k) { api('keyboard/key', { key: k }); }
function typeText(e) {
  const t = $('typed').value;
  if (!t && !e) return;
  api('keyboard/type', { text: t, enter: e });
  $('typed').value = '';
}

function touch(el, onmove, ontap) {
  let lx, ly, t0, moved = 0, pend = { x: 0, y: 0 }, busy = false;
  el.addEventListener('touchstart', e => {
    const t = e.touches[0];
    lx = t.clientX; ly = t.clientY; t0 = Date.now(); moved = 0;
    e.preventDefault();
  }, { passive: false });
  el.addEventListener('touchmove', e => {
    const t = e.touches[0];
    pend.x += (t.clientX - lx) * 1.6;
    pend.y += (t.clientY - ly) * 1.6;
    moved += Math.abs(t.clientX - lx) + Math.abs(t.clientY - ly);
    lx = t.clientX; ly = t.clientY;
    e.preventDefault();
    flush();
  }, { passive: false });
  el.addEventListener('touchend', () => {
    if (ontap && moved < 8 && Date.now() - t0 < 250) ontap();
  });
  async function flush() {
    if (busy) return;
    busy = true;
    const x = Math.round(pend.x), y = Math.round(pend.y);
    pend.x -= x; pend.y -= y;
    if (x || y) await onmove(x, y).catch(() => {});
    busy = false;
    if (Math.abs(pend.x) >= 1 || Math.abs(pend.y) >= 1) flush();
  }
}
touch($('pad'), (x, y) => api('mouse/move', { dx: x, dy: y }), () => click_('left'));
touch($('scroll'), (x, y) => api('mouse/scroll', { amount: Math.round(-y / 8) }));

/* Hardware Sliders & Power */
function setVol(v) { api('volume', { level: +v }); }
function setBri(v) { api('brightness', { level: +v }); }
function media(k, rep = 1) { for (let i = 0; i < rep; i++) api('media/' + k); }
function pw(action, name) {
  if (confirm(`Confirm ${name} on Host PC?`)) api('power/' + action).then(r => toast(r.msg || action));
}

function remoteUninstall() {
  if (!confirm("⚠️ PERMANENT UNINSTALL CONFIRMATION\n\nThis will completely remove Project-X-Nano from this PC:\n- Stop and terminate background service and watchdog\n- Remove autostart registry entries and scheduled tasks\n- Delete all program files and data folders\n\nAre you sure you want to completely uninstall?")) return;
  const pw = prompt("Enter master password to authorize uninstallation:");
  if (!pw) return;
  api('system/uninstall', { password: pw }).then(r => {
    if (r.ok) {
      alert("✅ " + r.msg + "\n\nConnection is now closed.");
      window.location.reload();
    } else {
      toast("❌ " + (r.error || "Uninstall failed"));
    }
  });
}
async function checkUpdate() {
  toast("Checking GitHub for updates...");
  const s = await api('system/update');
  if (s.ok && s.status) {
    if (s.status.has_update) {
      if (confirm(`New update available on GitHub (${s.status.latest_sha})!\n\nWould you like to download and apply it automatically now?`)) {
        toast("Downloading update from GitHub...");
        const res = await api('system/update', {}, 'POST');
        if (res.ok) {
          alert("✅ Update applied successfully! " + res.msg);
          window.location.reload();
        } else {
          toast("⚠ Update error: " + (res.error || "Failed to update"));
        }
      }
    } else {
      toast("✓ Up to date! Version: " + (s.status.local_version || "1.2.1"));
    }
  } else {
    toast("⚠ Could not reach GitHub update service");
  }
}

function emergencyLockdown() {
  const pw = prompt('EMERGENCY LOCKDOWN: Enter master password to confirm immediate lock, browser purge, and sign-out:');
  if (!pw) return;
  api('security/lockdown', { password: pw }).then(r => toast(r.msg || 'Lockdown engaged'));
}

/* ================= FILES & DRIVES ================= */
let curPath = '';
const fmt = n => n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n > 1e3 ? Math.round(n / 1e3) + ' KB' : n + ' B';

async function loadDrives() {
  try {
    const d = await api('drives');
    if (d.drives && d.drives.length) {
      $('drives').innerHTML = d.drives.map(x => `
        <button style="flex:initial;padding:6px 12px;font-size:12px" onclick="files('${x.mount.replace(/\\/g, '\\\\')}')">
          💾 <b>${x.mount}</b>${x.free_gb != null ? ` <small style="color:var(--text-muted)">(${x.free_gb} GB)</small>` : ''}
        </button>
      `).join('') + `<button style="flex:initial;padding:6px 12px;font-size:12px" onclick="files('')">🏠 Home</button>`;
    }
  } catch (e) {}
}
async function files(p) {
  const d = await api('files' + (p ? '?path=' + encodeURIComponent(p) : ''));
  if (d.error) return;
  curPath = d.path;
  $('fpath').textContent = d.path;
  const rows = (d.parent ? [{ name: '..', dir: true, up: d.parent }] : []).concat(d.items);
  $('files').innerHTML = '';
  rows.forEach(f => {
    const full = f.up || (d.path.replace(/[\\/]$/, '') + (d.path.includes('\\') ? '\\' : '/') + f.name);
    const r = document.createElement('div');
    r.className = 'proc';
    const s = document.createElement('span');
    s.textContent = (f.dir ? '📁 ' : '📄 ') + f.name + (f.dir ? '' : ' · ' + fmt(f.size));
    s.style.cursor = 'pointer';
    s.onclick = () => f.dir ? files(full) : 0;
    r.appendChild(s);
    if (f.name !== '..') {
      const w = document.createElement('span');
      if (!f.dir) {
        const o = document.createElement('button');
        o.textContent = '▶ Open';
        o.onclick = () => api('files/open', { path: full });
        const b = document.createElement('button');
        b.textContent = '⬇';
        b.onclick = () => location.href = '/api/files/download?path=' + encodeURIComponent(full);
        w.append(o, ' ', b, ' ');
      }
      const delBtn = document.createElement('button');
      delBtn.className = 'danger';
      delBtn.style.padding = '4px 8px';
      delBtn.style.fontSize = '12px';
      delBtn.style.color = '#ef4444';
      delBtn.textContent = '🗑';
      delBtn.title = 'Delete item';
      delBtn.onclick = (e) => {
        e.stopPropagation();
        deleteRemoteFile(full, f.name);
      };
      w.appendChild(delBtn);
      r.appendChild(w);
    }
    $('files').appendChild(r);
  });
}

async function deleteRemoteFile(fullPath, name) {
  if (!confirm(`Are you sure you want to permanently delete:\n${name}\n\nThis action cannot be undone.`)) return;
  let d = await api('files/delete', { path: fullPath, admin: false });
  if (d.ok) {
    toast('✓ ' + d.msg);
    files(curPath);
  } else {
    if (confirm(`Standard deletion failed: ${d.error || 'Access denied'}\n\nDo you want to force delete using Administrator authority?`)) {
      let dAdmin = await api('files/delete', { path: fullPath, admin: true });
      if (dAdmin.ok) {
        toast('✓ ' + dAdmin.msg);
        files(curPath);
      } else {
        toast('⚠ Admin delete error: ' + (dAdmin.error || 'Failed to delete'));
      }
    }
  }
}

async function upload() {
  const fs = $('upf').files;
  if (!fs.length) return;
  const fd = new FormData();
  fd.append('path', curPath);
  for (const f of fs) fd.append('files', f);
  const r = await fetch('/api/files/upload', { method: 'POST', body: fd });
  const d = await r.json();
  toast(d.error ? '⚠ ' + d.error : '✓ ' + d.msg);
  $('upf').value = '';
  files(curPath);
}

/* ================= FLEET MANAGEMENT ================= */
let fleetData = [];
async function fleetRefresh() {
  $('fleetList').innerHTML = '<span style="color:var(--text-muted);font-size:12px">Checking fleet node statuses…</span>';
  try {
    const d = await api('fleet');
    fleetData = d.fleet || [];
    $('fleetCount').textContent = `${fleetData.length} Node${fleetData.length === 1 ? '' : 's'}`;
    if ($('tabFleetCount')) $('tabFleetCount').textContent = fleetData.length;
    filterFleet();
  } catch (e) {
    $('fleetList').innerHTML = '<span style="color:var(--text-muted);font-size:12px">Error loading fleet nodes.</span>';
  }
}
function filterFleet() {
  const q = $('fleetSearch').value.toLowerCase().trim();
  const filtered = fleetData.filter(x => (x.name || '').toLowerCase().includes(q) || (x.url || '').toLowerCase().includes(q));
  if (!filtered.length) {
    $('fleetList').innerHTML = '<span style="color:var(--text-muted);font-size:12px;padding:8px 0">No matching nodes registered in fleet.</span>';
    return;
  }
  $('fleetList').innerHTML = filtered.map(x => {
    const isLocal = x.local;
    const badge = x.online ? '<span class="badge badge-green">ONLINE</span>' : '<span class="badge badge-red">OFFLINE</span>';
    const stats = x.online && x.cpu != null ? `<span style="color:var(--text-muted);font-size:11px"> · CPU ${x.cpu}% · RAM ${x.ram}%</span>` : '';
    const btn = isLocal ? '<span class="badge badge-green">PRIMARY HOST</span>' :
      `<span><button class="acc" style="padding:4px 10px;font-size:11px" onclick="window.open('${x.url}','_blank')">🎮 Control</button> <button class="red" style="padding:4px 8px;font-size:11px" onclick="removeFleetNode('${x.id}')">✕</button></span>`;
    return `<div class="proc" style="padding:10px">
      <div><b>${x.name}</b> ${badge} ${stats}<br><small style="color:var(--text-muted)">${x.url}</small></div>
      ${btn}
    </div>`;
  }).join('');
}
async function addFleetNode() {
  const name = $('fAddName').value.trim();
  const url = $('fAddUrl').value.trim();
  if (!url) { toast('Enter PC URL'); return; }
  const r = await api('fleet/add', { name, url });
  if (r.ok) {
    $('fAddName').value = ''; $('fAddUrl').value = ''; $('fleetAddBox').style.display = 'none';
    fleetRefresh();
  }
}
async function removeFleetNode(id) {
  if (!confirm('Remove PC from fleet registry?')) return;
  await api('fleet/remove', { id });
  fleetRefresh();
}
async function autoAddDiscovered() {
  const d = await api('discover');
  if (!d.devices || !d.devices.length) { toast('No other PCs found on network'); return; }
  let added = 0;
  for (const dev of d.devices) {
    const r = await api('fleet/add', { name: dev.name, url: dev.url });
    if (r.ok) added++;
  }
  toast(`Added ${added} device(s) to fleet`);
  fleetRefresh();
}
async function broadcastFleet(act) {
  if (!confirm(`Broadcast "${act}" to ALL fleet PCs?`)) return;
  const r = await api('fleet/broadcast', { action: act });
  if (r.msg) toast(r.msg);
}
async function discover() {
  $('devList').innerHTML = '<span style="color:var(--text-muted)">Scanning subnet for Project-X-Nano nodes…</span>';
  try {
    const d = await api('discover');
    if (!d.devices || !d.devices.length) {
      $('devList').innerHTML = `<span style="color:var(--text-muted)">No other Project-X-Nano nodes found on ${d.my_ip} subnet.</span>`;
      return;
    }
    $('devList').innerHTML = d.devices.map(dev => `
      <div class="proc"><span>💻 <b>${dev.name}</b> <small style="color:var(--text-muted)">(${dev.ip})</small></span>
      <span><button class="acc" onclick="window.open('${dev.url}','_blank')">🔗 Open</button></span></div>
    `).join('');
  } catch (e) {
    $('devList').innerHTML = '<span style="color:var(--text-muted)">Scan finished.</span>';
  }
}

/* ================= TERMINAL ================= */
function termView(s) {
  $('adminB').textContent = s.admin ? '🛡 ADMIN CONSOLE' : 'USER CONSOLE';
  $('adminB').className = s.admin ? 'badge badge-green' : 'badge';
  $('termOff').style.display = s.enabled ? 'none' : 'block';
  $('termLocked').style.display = s.enabled && !s.unlocked ? 'block' : 'none';
  $('termOn').style.display = s.enabled && s.unlocked ? 'block' : 'none';
  if (s.cwd) $('tcwd').textContent = s.cwd;
  if (!$('tshell').options.length) s.shells.forEach(x => $('tshell').add(new Option(x, x)));
}
async function termStatus() { try { termView(await api('terminal/status')); } catch (e) {} }
async function termUnlock() {
  const r = await fetch('/api/terminal/unlock', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: $('tpw').value })
  });
  const d = await r.json();
  toast(d.error ? '⚠ ' + d.error : '✓ ' + d.msg);
  $('tpw').value = '';
  termStatus();
}
async function termLock() { await api('terminal/lock', {}); termStatus(); }
async function termRun() {
  const c = $('tcmd').value.trim();
  if (!c) return;
  const o = $('tout');
  $('tcmd').value = '';
  o.textContent += '> ' + c + '\n';
  o.scrollTop = o.scrollHeight;
  const r = await fetch('/api/terminal/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cmd: c, shell: $('tshell').value })
  });
  const d = await r.json();
  if (d.error) {
    o.textContent += '⚠ ' + d.error + '\n';
    if (d.locked) termStatus();
  } else {
    o.textContent += (d.output || '') + (d.output && !d.output.endsWith('\n') ? '\n' : '');
    if (d.cwd) $('tcwd').textContent = d.cwd;
  }
  o.scrollTop = o.scrollHeight;
}
$('tcmd').addEventListener('keydown', e => { if (e.key === 'Enter') termRun(); });
$('tpw').addEventListener('keydown', e => { if (e.key === 'Enter') termUnlock(); });

/* ================= HARDWARE EXTRAS & AUTOSTART ================= */
async function autoGet() {
  const d = await api('autostart');
  $('autoB').textContent = '🚀 Start with PC: ' + (d.enabled ? 'ON' : 'OFF');
}
async function autoTog() {
  await api('autostart', { enabled: $('autoB').textContent.endsWith('OFF') });
  autoGet();
}
function askNotif() {
  if (window.isSecureContext && window.Notification) Notification.requestPermission().then(p => toast('Notifications: ' + p));
  else toast('Notifications require HTTPS or ntfy app');
}

/* ================= INITIALIZATION ================= */
let started = false;
async function init() {
  files('');
  loadDrives();
  fleetRefresh();
  discover();
  cmds();
  termStatus();
  autoGet();
  try {
    const a = await api('apps');
    $('apps').innerHTML = a.map(n => `<button onclick="api('launch',{name:'${n}'})">${n}</button>`).join('');
  } catch (e) {}
  try {
    const v = await api('volume');
    if (v.level != null) { $('vol').value = v.level; $('volVal').textContent = v.level + '%'; }
  } catch (e) {}
  try {
    const b = await api('brightness');
    if (b.level != null) { $('bri').value = b.level; $('briVal').textContent = b.level + '%'; }
  } catch (e) {}
  stats();
  if (!started) {
    started = true;
    setInterval(() => { if ($('main').style.display !== 'none') stats(); }, 4000);
  }
}

if ($('pw')) {
  $('pw').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      if ($('login2faBox') && $('login2faBox').style.display !== 'none' && $('loginTotp') && !$('loginTotp').value) {
        $('loginTotp').focus();
      } else {
        login();
      }
    }
  });
}

if ($('loginTotp')) {
  $('loginTotp').addEventListener('keydown', e => {
    if (e.key === 'Enter') login();
  });
  $('loginTotp').addEventListener('input', e => {
    if (e.target.value.trim().length === 6) login();
  });
}

if ($('totpConfirmCode')) {
  $('totpConfirmCode').addEventListener('keydown', e => {
    if (e.key === 'Enter') confirm2FA();
  });
  $('totpConfirmCode').addEventListener('input', e => {
    if (e.target.value.trim().length === 6) confirm2FA();
  });
}

if ($('chkRemember')) {
  $('chkRemember').checked = localStorage.getItem('pxn_remember') !== 'false';
  $('chkRemember').addEventListener('change', e => {
    if (!e.target.checked) {
      localStorage.removeItem('pxn_remember');
      localStorage.removeItem('pxn_saved_pw');
    }
  });
}

// Pre-check if 2FA is active on the server
fetch('/api/auth/state').then(r => r.json()).then(state => {
  if (state && state.totp_enabled) {
    if ($('login2faBox')) $('login2faBox').style.display = 'block';
  }
}).catch(() => {});

// Initial check: if already authenticated via session cookie or JWT, show dashboard immediately;
// otherwise, attempt auto-connect from saved credentials.
fetch('/api/stats').then(r => {
  if (r.ok) {
    show(true);
  } else {
    show(false);
    attemptAutoConnect();
  }
}).catch(() => {
  show(false);
  attemptAutoConnect();
});
</script></body></html>"""


@app.get("/api/system/update")
@login_required
def api_system_update_status():
    try:
        engine = IntegrityEngine(BASE)
        return jsonify(ok=True, status=engine.check_for_updates())
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.post("/api/system/update")
@login_required
def api_system_update_apply():
    try:
        engine = IntegrityEngine(BASE)
        res = engine.apply_update()
        return jsonify(ok=True, result=res, msg=f"Updated {res.get('updated_count', 0)} file(s) from GitHub.")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.get("/api/system/integrity")
@login_required
def api_system_integrity():
    missing = integrity_engine.check_missing_files()
    return jsonify(
        ok=len(missing) == 0,
        missing_count=len(missing),
        missing=[m[0] for m in missing]
    )


@app.get("/api/tunnel/url")
@login_required
def api_tunnel_url():
    import tunnel
    return jsonify(
        public_url=tunnel.get_public_url() or CFG.get("last_public_url", ""),
        report_url=CFG.get("tunnel_report_url", "")
    )


@app.post("/api/tunnel/config")
@login_required
def api_tunnel_config():
    d = request.get_json(silent=True) or {}
    report_url = str(d.get("report_url", "")).strip()
    if report_url and not report_url.startswith(("http://", "https://")):
        return jsonify(error="Invalid report URL: must start with http:// or https://"), 400
    CFG["tunnel_report_url"] = report_url
    save_cfg()
    return jsonify(ok=True, msg="Tunnel report URL saved")


@app.get("/")
def index():
    return PAGE
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()
def render_keepalive():
    """If deployed on Render, ping external URL every 10 min to prevent sleep on inactivity."""
    url = (os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KEEP_ALIVE_URL") or "").rstrip("/")
    if not url:
        return
    time.sleep(60)
    while True:
        try:
            req = urllib.request.Request(f"{url}/api/stats", headers={"User-Agent": "Render-KeepAlive"})
            with urllib.request.urlopen(req, timeout=15):
                pass
        except Exception:
            pass
        time.sleep(600)  # Ping every 10 minutes (Render sleeps at 15 minutes)
# Start background monitor and keepalive threads
try:
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=render_keepalive, daemon=True).start()
except Exception:
    pass
if __name__ == "__main__":
    if "--nuke" in sys.argv:
        perform_nuke()
        sys.exit(0)

    port = int(os.environ.get("PORT", CFG["port"]))
    tunnel_active = "--forward" in sys.argv or CFG.get("auto_forward", True)
    lan_opt_in = CFG.get("lan_opt_in", False)
    if tunnel_active and not lan_opt_in:
        host = "127.0.0.1"
    else:
        host = os.environ.get("HOST", CFG["host"])

    print("\n=== Project-X-Nano running ===")
    print(f"Server bound to:     http://{host}:{port}")
    print(f"Open on your phone:  http://{lan_ip()}:{port}")
    if FIRST_PASSWORD:
        print(f"Your password (shown once, change by deleting config.json): {FIRST_PASSWORD}")
    if tunnel_active and not lan_opt_in:
        print("[Security] Bound exclusively to 127.0.0.1 (tunnel active, LAN access restricted for defense in depth).")
    print("For outside-home access use Cloudflare/Ngrok Tunnel or Tailscale.\n")

    if tunnel_active:
        try:
            import tunnel
            def _launch_tunnel():
                time.sleep(1.0)
                tunnel.start_tunnel(
                    port=port,
                    report_url=CFG.get("tunnel_report_url", ""),
                    ngrok_auth_token=CFG.get("ngrok_token", "")
                )
            threading.Thread(target=_launch_tunnel, daemon=True).start()
        except Exception as e:
            print(f"[Tunnel] Error initializing tunnel: {e}")
    app.run(host=host, port=port, threaded=True)
