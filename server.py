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
DEFAULT_CONFIG = {
    "port": 8765,
    "host": "0.0.0.0",  # use 127.0.0.1 to allow only this PC
    "password_hash": "scrypt:32768:8:1$YEUInWwNr3gIINYC$f8cd567c2b4d283c8fac654b3492e2aff02c5af6ea6aecf0781573737ecd295af4e1a6f9b0eae0ee61faacc0e2b88845764d0b4ecb17075ff448a1b9f62920cd",
    "secret_key": "",
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
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
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
    if not cfg["secret_key"]:
        cfg["secret_key"] = secrets.token_hex(32)
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
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
# ---------------------------------------------------------------- auth
FAILS = {}  # ip -> (count, locked_until)
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            return jsonify(error="Not logged in"), 401
        return fn(*a, **kw)
    return wrapper
@app.post("/login")
@app.post("/api/login")
def login():
    ip = request.remote_addr
    count, locked = FAILS.get(ip, (0, 0))
    if time.time() < locked:
        return jsonify(error="Too many attempts. Wait a minute."), 429
    pw = (request.get_json(silent=True) or {}).get("password", "")
    if check_password_hash(CFG["password_hash"], pw):
        FAILS.pop(ip, None)
        session["ok"] = True
        session.permanent = True
        push_alert(f"New login from {ip}")
        return jsonify(ok=True)
    count += 1
    if count >= 3:
        push_alert(f"{count} failed login attempts from {ip}")
    FAILS[ip] = (count, time.time() + 60 if count >= 5 else 0)
    time.sleep(1)
    return jsonify(error="Wrong password"), 403
@app.post("/logout")
@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)
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
    if not check_password_hash(CFG["password_hash"], pw):
        push_alert(f"Failed emergency lockdown attempt from {request.remote_addr}")
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
@app.get("/api/processes")
@login_required
def api_processes():
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            procs.append({"pid": p.info["pid"], "name": p.info["name"], "mem": round(p.info["memory_percent"] or 0, 1)})
        except psutil.Error:
            pass
    procs.sort(key=lambda x: x["mem"], reverse=True)
    return jsonify(procs[:15])
@app.post("/api/kill")
@login_required
def api_kill():
    pid = int((request.get_json(silent=True) or {}).get("pid", 0))
    if pid in (0, 4, os.getpid()):
        return jsonify(error="Protected process"), 400
    try:
        psutil.Process(pid).terminate()
    except psutil.Error as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)
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
# ---------------------------------------------------------------- clipboard
@app.get("/api/clipboard")
@login_required
def api_clip_get():
    if pyperclip is None:
        return jsonify(error="Install pyperclip"), 500
    try:
        return jsonify(text=(pyperclip.paste() or "")[:5000])
    except Exception as e:
        return jsonify(error=f"Clipboard unavailable: {e}"), 500
@app.post("/api/clipboard")
@login_required
def api_clip_set():
    if pyperclip is None:
        return jsonify(error="Install pyperclip"), 500
    try:
        pyperclip.copy(str((request.get_json(silent=True) or {}).get("text", ""))[:5000])
    except Exception as e:
        return jsonify(error=f"Clipboard unavailable: {e}"), 500
    return jsonify(ok=True, msg="Copied on PC")
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
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                for name in ["Project-X-Nano", "RemotePC"]:
                    try:
                        winreg.DeleteValue(k, name)
                    except FileNotFoundError:
                        pass
            for name in ["Project-X-Nano", "RemotePC"]:
                subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], capture_output=True)
    except Exception:
        pass
    def delayed_exit():
        time.sleep(1.5)
        try:
            cleanup_cmds = ["timeout /t 3 /nobreak >nul"]
            target_dirs = []
            if "LOCALAPPDATA" in os.environ:
                target_dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Project-X-Nano")
                target_dirs.append(Path(os.environ["LOCALAPPDATA"]) / "RemotePC")
            target_dirs.append(Path(r"C:\RemotePC"))
            for d in target_dirs:
                if d.exists():
                    cleanup_cmds.append(f'rmdir /s /q "{d}"')
            try:
                exe_file = Path(sys.executable)
                if exe_file.is_file() and any(str(td).lower() in str(exe_file).lower() for td in target_dirs):
                    cleanup_cmds.append(f'del /f /q "{exe_file}"')
            except Exception:
                pass
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
def audit(text):
    with open(BASE / "audit.log", "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {request.remote_addr} {text}\n")
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
    key = "term:" + request.remote_addr
    count, locked = FAILS.get(key, (0, 0))
    if time.time() < locked:
        return jsonify(error="Too many attempts. Wait a minute."), 429
    pw = (request.get_json(silent=True) or {}).get("password", "")
    if not check_password_hash(CFG["password_hash"], pw):
        count += 1
        FAILS[key] = (count, time.time() + 60 if count >= 3 else 0)
        audit("terminal unlock FAILED")
        push_alert(f"Failed terminal unlock from {request.remote_addr}")
        time.sleep(1)
        return jsonify(error="Wrong password"), 403
    FAILS.pop(key, None)
    session["term_until"] = time.time() + TERM_UNLOCK_SECONDS
    audit("terminal unlocked")
    push_alert(f"Terminal unlocked from {request.remote_addr}")
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
    CONFIG_FILE.write_text(json.dumps(CFG, indent=2))
    return jsonify(ok=True, msg=f"Added '{name}' to fleet", id=node_id)
@app.post("/api/fleet/remove")
@login_required
def api_fleet_remove():
    d = request.get_json(silent=True) or {}
    node_id = str(d.get("id", "")).strip()
    fleet = CFG.get("fleet", [])
    CFG["fleet"] = [f for f in fleet if f.get("id") != node_id]
    CONFIG_FILE.write_text(json.dumps(CFG, indent=2))
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
    <button class="nav-tab" onclick="showTab('files', this)">📁 Files &amp; Drives</button>
    <button class="nav-tab" onclick="showTab('terminal', this)">💻 Terminal</button>
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
      <div class="row" style="margin-top:12px">
        <button class="red" style="font-weight:700" onclick="emergencyLockdown()">🚨 Emergency Lockdown</button>
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
  const opt = { method: body ? method : 'GET', headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  try {
    const res = await fetch('/api/' + path, opt);
    if (res.status === 401) {
      show(false);
      attemptAutoConnect();
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

async function login() {
  const pw = $('pw').value;
  if (!pw) return;
  try {
    const d = await api('login', { password: pw });
    if (d.ok) {
      if ($('chkRemember').checked) {
        localStorage.setItem('pxn_saved_pw', pw);
      } else {
        localStorage.removeItem('pxn_saved_pw');
      }
      $('pw').value = '';
      show(true);
      toast('✓ Connected to Host PC');
    } else {
      toast('⚠ ' + (d.error || 'Authentication Failed'));
    }
  } catch (e) {
    toast('⚠ Connection failed');
  }
}

async function attemptAutoConnect() {
  const savedPw = localStorage.getItem('pxn_saved_pw');
  if (!savedPw) return;
  try {
    const d = await api('login', { password: savedPw });
    if (d.ok) {
      show(true);
      toast('✓ Auto-connected to Host PC');
    }
  } catch (e) {}
}

async function logout() {
  localStorage.removeItem('pxn_saved_pw');
  await api('logout', {});
  show(false);
}

function updateHostServerPills() {
  const hostIp = location.hostname;
  const port = location.port || '8765';
  $('srvLanUrl').textContent = `http://${hostIp}:${port}`;
  // Check Cloudflare tunnel URL if any
  fetch('/api/fleet').then(r => r.json()).then(d => {
    // If tunnel report URL exists or stats report public url
  }).catch(()=>{});
}

function copyText(str) {
  navigator.clipboard ? navigator.clipboard.writeText(str).then(() => toast('✓ Copied: ' + str)) : prompt('Copy URL:', str);
}

/* ================= TAB NAVIGATION ================= */
function showTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  const target = $('tab-' + name);
  if (target) target.style.display = 'block';
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
    if (!f.dir) {
      const b = document.createElement('button');
      b.textContent = '⬇';
      b.onclick = () => location.href = '/api/files/download?path=' + encodeURIComponent(full);
      const o = document.createElement('button');
      o.textContent = '▶ Open';
      o.onclick = () => api('files/open', { path: full });
      const w = document.createElement('span');
      w.append(o, ' ', b);
      r.appendChild(w);
    }
    $('files').appendChild(r);
  });
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

$('pw').addEventListener('keydown', e => { if (e.key === 'Enter') login(); });

// Initial check: if already authenticated via session cookie, show dashboard immediately;
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
    CFG["tunnel_report_url"] = report_url
    CONFIG_FILE.write_text(json.dumps(CFG, indent=2), encoding="utf-8")
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
    port = int(os.environ.get("PORT", CFG["port"]))
    host = os.environ.get("HOST", CFG["host"])
    print("\n=== Project-X-Nano running ===")
    print(f"Open on your phone:  http://{lan_ip()}:{port}")
    if FIRST_PASSWORD:
        print(f"Your password (shown once, change by deleting config.json): {FIRST_PASSWORD}")
    print("Do NOT port-forward this to the internet. For outside-home access use Tailscale.\n")
    # Auto-start tunnel port forwarding if enabled or requested via --forward
    if "--forward" in sys.argv or CFG.get("auto_forward", True):
        try:
            import tunnel
            def _launch_tunnel():
                time.sleep(1.0)
                tunnel.start_tunnel(port=port, report_url=CFG.get("tunnel_report_url", ""))
            threading.Thread(target=_launch_tunnel, daemon=True).start()
        except Exception as e:
            print(f"[Tunnel] Error initializing tunnel: {e}")
    app.run(host=host, port=port, threaded=True)
