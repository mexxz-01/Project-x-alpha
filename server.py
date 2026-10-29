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

# ---------------------------------------------------------------- auth
FAILS = {}  # ip -> (count, locked_until)


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            return jsonify(error="Not logged in"), 401
        return fn(*a, **kw)

    return wrapper


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


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------------------------------------------------------------- helpers
def run(cmd, shell=False):
    subprocess.Popen(cmd, shell=shell, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def press_key(vk):
    if IS_WIN:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


VK = {
    "mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
    "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play_pause": 0xB3,
}


def power(action, delay=5):
    delay = max(0, int(delay))
    if IS_WIN:
        table = {
            "shutdown": ["shutdown", "/s", "/t", str(delay)],
            "restart": ["shutdown", "/r", "/t", str(delay)],
            "logoff": ["shutdown", "/l"],
            "hibernate": ["shutdown", "/h"],
            "cancel": ["shutdown", "/a"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
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
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    bat = psutil.sensors_battery()
    return jsonify(
        host=socket.gethostname(),
        os=f"{platform.system()} {platform.release()}",
        cpu=psutil.cpu_percent(interval=0.3),
        ram=vm.percent,
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
    if ImageGrab is None:
        return jsonify(error="Install pillow"), 500
    img = ImageGrab.grab().convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return Response(buf.getvalue(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


def generate_screen_stream():
    if ImageGrab is None:
        return
    try:
        while True:
            img = ImageGrab.grab().convert("RGB")
            img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=55)
            frame = buf.getvalue()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.08)
    except GeneratorExit:
        pass
    except Exception:
        pass


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


def need_gui():
    if pyautogui is None:
        return jsonify(error="Install pyautogui (pip install pyautogui) and run in a desktop session"), 500
    return None


@app.post("/api/mouse/move")
@login_required
def api_mouse_move():
    if (err := need_gui()):
        return err
    d = request.get_json(silent=True) or {}
    dx, dy = int(d.get("dx", 0)), int(d.get("dy", 0))
    pyautogui.moveRel(max(-500, min(500, dx)), max(-500, min(500, dy)), _pause=False)
    return jsonify(ok=True)


@app.post("/api/mouse/click")
@login_required
def api_mouse_click():
    if (err := need_gui()):
        return err
    d = request.get_json(silent=True) or {}
    button = d.get("button", "left")
    if button not in ("left", "right", "middle"):
        return jsonify(error="bad button"), 400
    pyautogui.click(button=button, clicks=2 if d.get("double") else 1)
    return jsonify(ok=True)


@app.post("/api/mouse/scroll")
@login_required
def api_mouse_scroll():
    if (err := need_gui()):
        return err
    amount = int((request.get_json(silent=True) or {}).get("amount", 0))
    pyautogui.scroll(max(-50, min(50, amount)) * 40)
    return jsonify(ok=True)


@app.post("/api/keyboard/type")
@login_required
def api_type():
    if (err := need_gui()):
        return err
    d = request.get_json(silent=True) or {}
    text = str(d.get("text", ""))[:1000]
    pyautogui.write(text, interval=0.01)
    if d.get("enter"):
        pyautogui.press("enter")
    return jsonify(ok=True)


@app.post("/api/keyboard/key")
@login_required
def api_key():
    if (err := need_gui()):
        return err
    key = str((request.get_json(silent=True) or {}).get("key", "")).lower()
    if key in ALLOWED_KEYS:
        pyautogui.press(key)
    elif key in ALLOWED_HOTKEYS:
        pyautogui.hotkey(*key.split("+"))
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
def _win_volume():
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    comtypes.CoInitialize()
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):  # newer pycaw
        return dev.EndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))


@app.get("/api/volume")
@login_required
def api_volume_get():
    try:
        if IS_WIN:
            return jsonify(level=round(_win_volume().GetMasterVolumeLevelScalar() * 100))
    except Exception:
        pass
    return jsonify(level=None)


@app.post("/api/volume")
@login_required
def api_volume_set():
    level = max(0, min(100, int((request.get_json(silent=True) or {}).get("level", 0))))
    try:
        if IS_WIN:
            _win_volume().SetMasterVolumeLevelScalar(level / 100, None)
        elif IS_MAC:
            run(["osascript", "-e", f"set volume output volume {level}"])
        else:
            run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
    except Exception as e:
        return jsonify(error=f"Volume control unavailable: {e}"), 500
    return jsonify(ok=True)


@app.get("/api/brightness")
@login_required
def api_bri_get():
    try:
        import screen_brightness_control as sbc

        return jsonify(level=int(sbc.get_brightness()[0]))
    except Exception:
        return jsonify(level=None)


@app.post("/api/brightness")
@login_required
def api_bri_set():
    level = max(0, min(100, int((request.get_json(silent=True) or {}).get("level", 50))))
    try:
        import screen_brightness_control as sbc

        sbc.set_brightness(level)
    except Exception as e:
        return jsonify(error=f"Brightness unavailable (laptop/DDC monitors only): {e}"), 500
    return jsonify(ok=True)


# ---------------------------------------------------------------- sound, speech, webcam
def _play(kind):
    if IS_WIN:
        import winsound

        if kind == "alarm":
            for _ in range(8):
                winsound.Beep(1300, 300)
                winsound.Beep(800, 300)
        else:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    elif IS_MAC:
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
    else:
        print("\a", end="")


@app.post("/api/sound")
@login_required
def api_sound():
    kind = (request.get_json(silent=True) or {}).get("kind", "beep")
    threading.Thread(target=_play, args=("alarm" if kind == "alarm" else "beep",), daemon=True).start()
    return jsonify(ok=True, msg="Playing sound on PC")


@app.post("/api/speak")
@login_required
def api_speak():
    text = str((request.get_json(silent=True) or {}).get("text", ""))[:300]
    if not text:
        return jsonify(error="empty"), 400
    env = dict(os.environ, REMOTE_TEXT=text)  # passed via env: no shell injection
    if IS_WIN:
        ps = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:REMOTE_TEXT)"
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=0x08000000)
    elif IS_MAC:
        subprocess.Popen(["say", text])
    else:
        subprocess.Popen(["espeak", text])
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
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
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
    if (err := need_gui()):
        return err
    d = request.get_json(silent=True) or {}
    fx = max(0.0, min(1.0, float(d.get("x", 0))))
    fy = max(0.0, min(1.0, float(d.get("y", 0))))
    w, h = pyautogui.size()
    pyautogui.click(int(fx * (w - 1)), int(fy * (h - 1)), button="right" if d.get("right") else "left")
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
            exe_path = Path(sys.executable)
            if "LOCALAPPDATA" in os.environ and str(Path(os.environ["LOCALAPPDATA"])) in str(exe_path):
                subprocess.Popen(f'cmd /c "timeout /t 2 /nobreak >nul & del /f /q \"{exe_path}\""', shell=True)
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return jsonify(ok=True, msg="Project-X-Nano uninstalled successfully. Background server stopped.")


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
    # `cd` is handled here so the working folder persists between commands
    m = re.match(r'^cd(?:\s+/d)?\s+"?([^"]+?)"?$', cmd, re.I)
    if m:
        new = (Path(TERM["cwd"]) / m.group(1)).expanduser().resolve()
        if new.is_dir():
            TERM["cwd"] = str(new)
            return jsonify(output="", cwd=TERM["cwd"], code=0)
        return jsonify(output="The system cannot find the path specified.", cwd=TERM["cwd"], code=1)
    if IS_WIN:
        argv = (["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
                if shell == "powershell" else ["cmd", "/c", cmd])
    else:
        argv = ["bash", "-c", cmd]
    timeout = int(CFG.get("terminal_timeout", 60))
    try:
        r = subprocess.run(
            argv, cwd=TERM["cwd"], capture_output=True, text=True, errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
            creationflags=0x08000000 if IS_WIN else 0,
        )
        out = (r.stdout or "") + (r.stderr or "")
        code = r.returncode
    except subprocess.TimeoutExpired:
        out, code = f"(stopped after {timeout}s: interactive or long-running commands aren't supported)", -1
    session["term_until"] = time.time() + TERM_UNLOCK_SECONDS  # keep alive while in use
    return jsonify(output=out[-20000:], cwd=TERM["cwd"], code=code)


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
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        res = s.connect_ex((ip, port))
        s.close()
        if res == 0:
            name = ip
            try:
                req = urllib.request.Request(
                    f"http://{ip}:{port}/api/stats",
                    headers={"User-Agent": "RemotePC-Discovery"}
                )
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        name = data.get("host", ip)
            except Exception:
                pass
            return {"ip": ip, "port": port, "name": name, "url": f"http://{ip}:{port}"}
    except Exception:
        pass
    return None


def discover_network_devices():
    found = []
    my_ip = lan_ip()
    candidates = set()
    try:
        out = subprocess.check_output(["arp", "-a"], text=True, timeout=2)
        for line in out.splitlines():
            m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
            if m:
                ip = m.group(1)
                if not ip.startswith("224.") and not ip.startswith("239.") and not ip.endswith(".255"):
                    candidates.add(ip)
    except Exception:
        pass

    if my_ip and my_ip != "127.0.0.1":
        parts = my_ip.split(".")
        base = ".".join(parts[:3])
        for i in range(1, 255):
            candidates.add(f"{base}.{i}")

    candidates.discard(my_ip)
    candidates.discard("127.0.0.1")

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = pool.map(lambda ip: scan_device(ip, CFG.get("port", 8765)), candidates)
        for r in results:
            if r:
                found.append(r)
    return found


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
    url = node.get("url", "").rstrip("/")
    res = {
        "id": node.get("id"),
        "name": node.get("name") or url,
        "url": url,
        "group": node.get("group", "Default"),
        "online": False,
        "cpu": None,
        "ram": None,
        "os": None,
        "battery": None,
    }
    if not url:
        return res
    try:
        req = urllib.request.Request(f"{url}/api/stats", headers={"User-Agent": "RemotePC-Fleet"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                res["online"] = True
                res["cpu"] = data.get("cpu")
                res["ram"] = data.get("ram")
                res["os"] = data.get("os")
                res["battery"] = data.get("battery")
                if not node.get("name") or node.get("name") == url:
                    res["name"] = data.get("host", node.get("name"))
    except Exception:
        pass
    return res


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
        "ram": psutil.virtual_memory().percent,
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

    def send_action(node):
        url = node.get("url", "").rstrip("/")
        try:
            req = urllib.request.Request(
                f"{url}/api/power/{action}",
                data=json.dumps({"delay": 10}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3.0)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=min(30, max(1, len(fleet)))) as pool:
        list(pool.map(send_action, fleet))
    return jsonify(ok=True, msg=f"Broadcasted '{action}' to all fleet PCs")


# ---------------------------------------------------------------- UI
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project-X-Nano</title>
<link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#090a10">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Project-X-Nano">
<style>
:root {
  --bg: #090b12;
  --bg-gradient: radial-gradient(circle at 50% 0%, #161c2e 0%, #090b12 80%);
  --surface: #131722;
  --surface-hover: #1a1f30;
  --card-border: rgba(255, 255, 255, 0.08);
  --fg: #f8fafc;
  --mut: #94a3b8;
  --acc: #3b82f6;
  --acc-glow: rgba(59, 130, 246, 0.35);
  --acc-gradient: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  --red: #ef4444;
  --red-bg: rgba(239, 68, 68, 0.12);
  --grn: #10b981;
  --grn-bg: rgba(16, 185, 129, 0.12);
  --amber: #f59e0b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  background-image: var(--bg-gradient);
  background-attachment: fixed;
  color: var(--fg);
  font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif;
  padding: 16px;
  max-width: 860px;
  margin: auto;
  min-height: 100vh;
}
/* Top App Header */
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0 16px;
  border-bottom: 1px solid var(--card-border);
  margin-bottom: 14px;
}
.app-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.brand-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 9999px;
  background: var(--acc-gradient);
  color: #fff;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--grn);
  box-shadow: 0 0 10px var(--grn);
  display: inline-block;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
/* Tabs Navigation */
.nav-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 8px;
  margin-bottom: 14px;
  scrollbar-width: none;
}
.nav-tabs::-webkit-scrollbar { display: none; }
.nav-tab {
  flex: 0 0 auto;
  background: var(--surface);
  border: 1px solid var(--card-border);
  color: var(--mut);
  padding: 8px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.nav-tab:hover {
  background: var(--surface-hover);
  color: var(--fg);
}
.nav-tab.active {
  background: var(--acc-gradient);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 14px var(--acc-glow);
}
/* Cards */
.card {
  background: var(--surface);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  padding: 16px;
  margin-bottom: 14px;
  box-shadow: 0 8px 24px -4px rgba(0,0,0,0.4);
  transition: border-color 0.2s ease;
}
.card:hover {
  border-color: rgba(255,255,255,0.12);
}
.card h2 {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--mut);
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
@media (max-width: 640px) {
  .grid-2 { grid-template-columns: 1fr; }
  .grid { grid-template-columns: repeat(2, 1fr); }
}
/* Buttons & Inputs */
button {
  font: inherit;
  border-radius: 10px;
  border: 1px solid var(--card-border);
  padding: 10px 12px;
  background: #1c2132;
  color: var(--fg);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
button:hover {
  background: #23293d;
  border-color: rgba(255,255,255,0.15);
}
button:active {
  transform: scale(0.97);
}
button.acc {
  background: var(--acc-gradient);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 12px var(--acc-glow);
}
button.acc:hover {
  filter: brightness(1.1);
}
button.red {
  background: var(--red-bg);
  color: var(--red);
  border-color: rgba(239, 68, 68, 0.25);
}
button.red:hover {
  background: rgba(239, 68, 68, 0.2);
}
input, textarea, select {
  font: inherit;
  width: 100%;
  background: #0d101a;
  border: 1px solid var(--card-border);
  border-radius: 10px;
  padding: 10px 12px;
  color: var(--fg);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
input:focus, textarea:focus, select:focus {
  border-color: var(--acc);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.row > * { flex: 1; }
/* Metrics & Progress Bars */
.stat-box {
  background: #0d101a;
  border: 1px solid var(--card-border);
  border-radius: 12px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.stat-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--mut);
  margin-bottom: 6px;
}
.bar {
  height: 6px;
  background: #1c2132;
  border-radius: 4px;
  overflow: hidden;
}
.bar > i {
  display: block;
  height: 100%;
  background: var(--acc-gradient);
  border-radius: 4px;
  transition: width 0.4s ease;
}
.bar-ram > i { background: linear-gradient(90deg, #8b5cf6, #ec4899); }
.bar-disk > i { background: linear-gradient(90deg, #10b981, #14b8a6); }
/* Custom range slider */
input[type=range] {
  -webkit-appearance: none;
  appearance: none;
  background: #1c2132;
  height: 8px;
  border-radius: 4px;
  padding: 0;
  cursor: pointer;
}
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--acc);
  box-shadow: 0 2px 8px var(--acc-glow);
  cursor: pointer;
}
/* Items & Process List */
.proc {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  background: #0d101a;
  border: 1px solid var(--card-border);
  border-radius: 10px;
  margin-bottom: 6px;
  font-size: 13px;
  transition: all 0.15s ease;
}
.proc:hover {
  border-color: rgba(255,255,255,0.12);
}
.badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 6px;
  font-weight: 600;
}
.badge-green { background: var(--grn-bg); color: var(--grn); }
.badge-red { background: var(--red-bg); color: var(--red); }
#toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 20, 32, 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.12);
  color: #fff;
  padding: 10px 20px;
  border-radius: 30px;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  display: none;
  z-index: 9999;
}
img { width: 100%; border-radius: 12px; margin-top: 8px; }
</style></head><body>

<!-- Login Modal -->
<div id="login" class="card" style="display:none;max-width:380px;margin:80px auto">
  <div style="text-align:center;margin-bottom:16px">
    <img src="/favicon.png" style="width:54px;height:54px;margin-bottom:10px;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,0.4)" alt="Project-X-Nano Logo">
    <h1 style="font-size:22px;margin:0">Project-X-Nano</h1>
    <p style="color:var(--mut);font-size:13px;margin:4px 0 0">Enter your master password to authenticate</p>
  </div>
  <input id="pw" type="password" placeholder="Enter Master Password" style="margin-bottom:12px">
  <button class="acc" style="width:100%" onclick="login()">Log In</button>
  <div style="text-align:center;margin-top:16px">
    <a href="/download/apk" style="color:var(--acc);font-size:12px;text-decoration:none;display:inline-flex;align-items:center;gap:6px">
      <span>📱</span> Download Android Controller APK
    </a>
  </div>
</div>

<!-- Main Application -->
<div id="main" style="display:none">
  <!-- Top App Header -->
  <header class="app-header">
    <div class="app-brand">
      <img src="/favicon.png" style="width:26px;height:26px;border-radius:6px;vertical-align:middle" alt="Logo">
      <span id="host">Project-X-Nano</span>
      <span class="brand-badge">NANO FLEET</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <a href="/download/apk" class="btn" style="text-decoration:none;padding:5px 10px;font-size:12px;background:var(--srf2);color:var(--txt);border:1px solid var(--brd);border-radius:6px;display:inline-flex;align-items:center;gap:4px">
        <span>📱</span> Android APK
      </a>
      <span class="pulse-dot"></span>
      <span style="font-size:12px;color:var(--grn);font-weight:600">ONLINE</span>
      <button style="padding:5px 10px;font-size:12px" onclick="logout()">Log out</button>
    </div>
  </header>

  <!-- Modern Navigation Tabs -->
  <nav class="nav-tabs">
    <button class="nav-tab active" onclick="showTab('overview', this)">📊 Overview</button>
    <button class="nav-tab" onclick="showTab('fleet', this)">👥 Fleet (<span id="tabFleetCount">1</span>)</button>
    <button class="nav-tab" onclick="showTab('screen', this)">📺 Screen &amp; Cam</button>
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
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-top:8px">
          <span id="osT">Windows</span>
          <span id="batT">🔋 Checking…</span>
        </div>
      </div>

      <!-- Quick Commands -->
      <div class="card">
        <h2>⚡ Quick Commands</h2>
        <div class="grid" id="cmds"></div>
        <pre id="cmdout" style="white-space:pre-wrap;font-size:11px;color:var(--mut);background:#0d101a;border:1px solid var(--card-border);border-radius:10px;padding:8px;max-height:140px;overflow:auto;margin:8px 0 0"></pre>
      </div>
    </div>

    <!-- App Launchers & Web -->
    <div class="card">
      <h2>🚀 App Launchers &amp; Web Navigation</h2>
      <div class="row" style="margin-bottom:10px">
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

  <!-- 2. FLEET TAB -->
  <div id="tab-fleet" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>👥 Multi-PC Fleet Manager</span>
        <span id="fleetCount" class="badge badge-green">1 Active Node</span>
      </h2>
      <div class="row" style="margin-bottom:10px">
        <input id="fleetSearch" placeholder="🔍 Search fleet (by hostname, IP, or group)…" oninput="filterFleet()">
        <button onclick="fleetRefresh()" style="flex:0 0 100px">🔄 Refresh</button>
        <button class="acc" onclick="$('fleetAddBox').style.display=$('fleetAddBox').style.display==='none'?'block':'none'" style="flex:0 0 90px">➕ Add PC</button>
      </div>
      
      <div id="fleetAddBox" style="display:none;background:#0d101a;padding:12px;border-radius:12px;margin-bottom:12px;border:1px solid var(--card-border)">
        <div style="font-weight:600;margin-bottom:8px">Register Remote Node</div>
        <input id="fAddName" placeholder="PC Name (e.g. Gaming PC, Office Laptop)" style="margin-bottom:8px">
        <input id="fAddUrl" placeholder="Node URL (e.g. http://192.168.1.50:8765 or Tailscale IP)" style="margin-bottom:8px">
        <div class="row">
          <button class="acc" onclick="addFleetNode()">Save Node</button>
          <button onclick="$('fleetAddBox').style.display='none'">Cancel</button>
        </div>
      </div>

      <div id="fleetList" style="display:flex;flex-direction:column;gap:8px;max-height:360px;overflow-y:auto"></div>

      <div class="row" style="margin-top:12px">
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
      <div id="devList" class="stat" style="flex-direction:column;gap:6px">Scanning subnet…</div>
    </div>
  </div>

  <!-- 3. SCREEN & CAMERA TAB -->
  <div id="tab-screen" class="tab-content" style="display:none">
    <!-- Live Desktop Screen -->
    <div class="card">
      <h2>
        <span>🖥️ Live Screen View</span>
        <span id="screenStatusBadge" class="badge badge-green" style="display:none">LIVE STREAM</span>
      </h2>
      <div class="row">
        <button id="liveB" class="acc" onclick="toggleScreenStream()">▶ Start Live Stream</button>
        <button onclick="shot()">📸 Take Snapshot</button>
        <button id="tapB" onclick="toggleTap()">🎯 Tap-to-Click: OFF</button>
      </div>
      <img id="shot" style="display:none;cursor:crosshair;box-shadow:0 6px 20px rgba(0,0,0,0.5)">
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

  <!-- 4. CONTROLS TAB -->
  <div id="tab-controls" class="tab-content" style="display:none">
    <!-- Touchpad -->
    <div class="card">
      <h2>🖱️ Virtual Touchpad Trackpad</h2>
      <div style="display:flex;gap:10px">
        <div id="pad" style="flex:1;height:220px;background:#0d101a;border:1px dashed #2d3748;border-radius:14px;touch-action:none;display:flex;align-items:center;justify-content:center;color:#64748b;user-select:none;font-weight:500">
          Touch &amp; Drag to Move Cursor · Tap to Click
        </div>
        <div id="scroll" style="width:50px;height:220px;background:#0d101a;border:1px dashed #2d3748;border-radius:14px;touch-action:none;display:flex;align-items:center;justify-content:center;color:#64748b;user-select:none;font-size:18px">
          ↕
        </div>
      </div>
      <div class="grid" style="margin-top:10px">
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
      <div class="grid" style="margin-top:10px">
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
      <div class="grid" style="margin-bottom:12px">
        <button onclick="media('prev')">⏮ Prev</button>
        <button onclick="media('play_pause')">⏯ Play/Pause</button>
        <button onclick="media('next')">⏭ Next</button>
        <button onclick="media('vol_down',3)">🔉 Volume −</button>
        <button onclick="media('mute')">🔇 Mute</button>
        <button onclick="media('vol_up',3)">🔊 Volume +</button>
      </div>
      <div style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-bottom:6px">
          <span>🔊 Master Volume</span><span id="volVal">50%</span>
        </div>
        <input id="vol" type="range" min="0" max="100" onchange="setVol(this.value);$('volVal').textContent=this.value+'%'">
      </div>
      <div style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-bottom:6px">
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
        <button class="red" onclick="pw('logoff','Sign out')">🚪 Sign Out</button>
        <button onclick="pw('lock')">🔒 Lock Screen</button>
        <button onclick="pw('sleep','Sleep')">🌙 Sleep</button>
        <button onclick="pw('hibernate','Hibernate')">❄️ Hibernate</button>
        <button class="acc" onclick="pw('cancel')" style="grid-column:span 3">✋ Abort Pending Shutdown</button>
      </div>
      <div class="row" style="margin-top:10px">
        <input id="mins" type="number" value="30" min="1" placeholder="Minutes">
        <button onclick="timer('shutdown')">Shutdown in…</button>
        <button onclick="timer('restart')">Restart in…</button>
      </div>
    </div>

    <!-- Emergency Theft Lockdown Card -->
    <div class="card" style="border:1px solid rgba(245,158,11,0.35);background:rgba(245,158,11,0.05);margin-top:16px">
      <h2 style="color:#fbbf24"><span>🚨 Emergency Theft Lockdown</span></h2>
      <p style="font-size:12px;color:var(--mut);margin-bottom:12px;line-height:1.5">
        Protect your accounts if your laptop is lost or stolen. Instantly terminates open web browsers (Chrome, Edge, Firefox, Brave) to wipe active session tokens, then locks the screen and signs out of Windows.
      </p>
      <button class="red" style="width:100%;padding:10px;font-weight:600;background:#d97706" onclick="emergencyLockdown()">🚨 Trigger Emergency Lockdown</button>
    </div>

    <!-- Remote Uninstall Card -->
    <div class="card" style="border:1px solid rgba(239,68,68,0.3);background:rgba(239,68,68,0.05);margin-top:16px">
      <h2 style="color:#f87171"><span>⚠️ Remote System Uninstaller</span></h2>
      <p style="font-size:12px;color:var(--mut);margin-bottom:12px;line-height:1.5">
        Completely remove Project-X-Nano from this PC remotely. Removes autostart registry, deletes scheduled tasks, cleans firewall rules, and terminates the background process.
      </p>
      <button class="red" style="width:100%;padding:10px;font-weight:600" onclick="remoteUninstall()">🗑️ Uninstall Project-X-Nano Remotely</button>
    </div>
  </div>

  <!-- 5. FILES TAB -->
  <div id="tab-files" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>📁 Multi-Drive File Explorer</span>
        <button onclick="files(cur)" style="padding:4px 8px;font-size:11px">🔄 Refresh</button>
      </h2>
      <div id="drives" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px"></div>
      <div id="fpath" style="font-size:12px;font-family:monospace;background:#0d101a;padding:8px 10px;border-radius:8px;border:1px solid var(--card-border);margin-bottom:8px;word-break:break-all"></div>
      <div id="files" style="max-height:360px;overflow-y:auto"></div>
      <div class="row" style="margin-top:10px">
        <input type="file" id="upf" multiple style="background:#0d101a">
        <button class="acc" onclick="upload()" style="flex:0 0 130px">⬆ Upload to PC</button>
      </div>
    </div>

    <!-- Clipboard Sync -->
    <div class="card">
      <h2>📋 Bi-Directional Clipboard Sync</h2>
      <textarea id="clip" rows="3" placeholder="Clipboard content…"></textarea>
      <div class="row">
        <button onclick="clipGet()">⬇ Pull from PC</button>
        <button class="acc" onclick="clipSet()">⬆ Push to PC</button>
        <button onclick="clipCopy()">📋 Copy on Phone</button>
      </div>
    </div>
  </div>

  <!-- 6. TERMINAL TAB -->
  <div id="tab-terminal" class="tab-content" style="display:none">
    <div class="card">
      <h2>
        <span>💻 Remote Terminal Console</span>
        <span id="adminB" class="badge badge-green">ADMIN SHELL</span>
      </h2>
      <div id="termOff" style="display:none;color:var(--amber);font-size:13px;padding:8px 0">
        Terminal is disabled in configuration.
      </div>
      <div id="termLocked" style="display:none;background:#0d101a;padding:14px;border-radius:12px;border:1px solid var(--card-border)">
        <div style="font-size:13px;color:var(--mut);margin-bottom:8px">🔐 Re-enter your password to unlock the terminal console (10 min session)</div>
        <input id="tpw" type="password" placeholder="Enter Master Password" style="margin-bottom:8px">
        <button class="acc" onclick="termUnlock()" style="width:100%">🔓 Unlock Console</button>
      </div>
      <div id="termOn" style="display:none">
        <pre id="tout" style="white-space:pre-wrap;word-break:break-all;font-size:12px;font-family:'JetBrains Mono',Consolas,monospace;background:#080a10;border:1px solid var(--card-border);border-radius:12px;padding:12px;height:260px;overflow:auto;margin:0 0 8px;color:#cbd5e1"></pre>
        <div id="tcwd" style="font-size:11px;font-family:monospace;color:var(--mut);margin-bottom:6px;word-break:break-all"></div>
        <div class="row">
          <select id="tshell" style="flex:0 0 130px"></select>
          <input id="tcmd" placeholder="Enter shell command…" autocapitalize="off" autocorrect="off" spellcheck="false" style="flex:3">
          <button class="acc" onclick="termRun()" style="flex:0 0 80px">▶ Run</button>
          <button onclick="termLock()" style="flex:0 0 80px">🔒 Lock</button>
        </div>
      </div>
    </div>

    <!-- Active Processes -->
    <div class="card">
      <h2>
        <span>⚙️ Active System Processes</span>
        <button onclick="procs()" style="padding:4px 8px;font-size:11px">🔄 Refresh</button>
      </h2>
      <div id="procs" style="max-height:260px;overflow-y:auto"></div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const $=id=>document.getElementById(id);
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',2600)}

function showTab(id, btn){
  document.querySelectorAll('.tab-content').forEach(el=>el.style.display='none');
  document.querySelectorAll('.nav-tab').forEach(el=>el.classList.remove('active'));
  const target=$('tab-'+id);
  if(target) target.style.display='block';
  if(btn) btn.classList.add('active');
}

async function api(path,body){
  const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(r.status===401){show(false);throw 0}
  const ct=r.headers.get('content-type')||'';
  const d=ct.includes('json')?await r.json():r;
  if(d.error)toast('⚠ '+d.error);else if(d.msg)toast('✓ '+d.msg);return d}

function show(ok){$('login').style.display=ok?'none':'block';$('main').style.display=ok?'block':'none';if(ok){init()}}
async function login(){const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('pw').value})});
  if(r.ok){$('pw').value='';show(true)}else toast((await r.json()).error)}
async function logout(){await api('logout',{});show(false)}
function pw(a,label){if(label&&!confirm(label+' the PC?'))return;api('power/'+a,{delay:5})}
async function remoteUninstall(){
  if(!confirm('⚠️ PERMANENT ACTION:\nAre you sure you want to completely uninstall Project-X-Nano from this PC remotely?\n\n- Windows Autostart will be removed\n- Scheduled tasks deleted\n- Firewall rules cleaned up\n- Background server terminated'))return;
  toast('Uninstalling Project-X-Nano...');
  try {
    const r = await api('system/uninstall', {});
    alert('✅ ' + (r.msg || 'Project-X-Nano uninstalled successfully.'));
    location.reload();
  } catch(e) {
    alert('Project-X-Nano uninstalled and process terminated.');
  }
}
async function emergencyLockdown(){
  const pw = prompt("⚠️ EMERGENCY LOCKDOWN CONFIRMATION:\n\nThis will force-terminate all open web browsers to protect your logged-in accounts, lock the screen, and sign out of Windows.\n\nEnter your Master Password to execute:");
  if(!pw) return;
  toast("Executing Emergency Lockdown...");
  try {
    const r = await fetch('/api/security/lockdown', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw})
    });
    const d = await r.json();
    if(d.ok) {
      alert("🔒 " + d.msg);
    } else {
      alert("❌ " + (d.error || "Lockdown failed"));
    }
  } catch(e) {
    alert("Emergency Lockdown sent. Session terminated.");
  }
}
function timer(a){api('timer',{action:a,minutes:+$('mins').value})}
function media(k,t){api('media/'+k,{times:t||1})}
function openUrl(){api('open_url',{url:$('url').value});toast('Opening link…')}
function sendMsg(){api('message',{text:$('msg').value});$('msg').value=''}

/* screen streaming & snapshots */
let screenStreaming=false;
function toggleScreenStream(){
  screenStreaming=!screenStreaming;
  const i=$('shot');
  const badge=$('screenStatusBadge');
  if(screenStreaming){
    i.style.display='block';
    i.src='/api/stream/screen?t='+Date.now();
    $('liveB').textContent='⏹ Stop Stream';
    $('liveB').classList.remove('acc');$('liveB').classList.add('red');
    if(badge) badge.style.display='inline-block';
  }else{
    i.src='';i.style.display='none';
    $('liveB').textContent='▶ Start Live Stream';
    $('liveB').classList.remove('red');$('liveB').classList.add('acc');
    if(badge) badge.style.display='none';
  }
}
function shot(){
  if(screenStreaming)toggleScreenStream();
  const i=$('shot');i.style.display='block';i.src='/api/screenshot?'+Date.now();
}

/* camera streaming & snapshots */
let camStreaming=false;
function toggleCamStream(){
  camStreaming=!camStreaming;
  const i=$('camimg');
  const badge=$('camStatusBadge');
  if(camStreaming){
    i.style.display='block';
    i.src='/api/stream/webcam?t='+Date.now();
    $('camB').textContent='⏹ Stop Camera';
    $('camB').classList.remove('acc');$('camB').classList.add('red');
    if(badge) badge.style.display='inline-block';
  }else{
    i.src='';i.style.display='none';
    $('camB').textContent='📹 Start Live Camera';
    $('camB').classList.remove('red');$('camB').classList.add('acc');
    if(badge) badge.style.display='none';
  }
}
function camShot(){
  if(camStreaming)toggleCamStream();
  const i=$('camimg');i.style.display='block';i.src='/api/webcam?'+Date.now();
}

async function stats(){try{const s=await api('stats');$('host').textContent=s.host;
  for(const k of['cpu','ram','disk']){$(k).style.width=s[k]+'%';$(k+'T').textContent=s[k]+'%'}
  $('osT').textContent=s.os+' · Uptime: '+Math.floor(s.uptime_min/60)+'h '+s.uptime_min%60+'m';
  $('batT').textContent=s.battery?('🔋 '+s.battery.percent+'%'+(s.battery.plugged?' ⚡':'')):''}catch(e){}}
async function procs(){const p=await api('processes');$('procs').innerHTML=p.map(x=>
  `<div class="proc"><span><b>${x.name}</b> <small style="color:var(--mut)">#${x.pid} · RAM ${x.mem}%</small></span><span><button onclick="watch('${x.name.replace(/'/g,'')}')">🔔 Watch</button> <button class="red" onclick="kill(${x.pid},'${x.name.replace(/'/g,'')}')">End</button></span></div>`).join('')}
function watch(n){api('watch',{name:n})}
function kill(pid,n){if(confirm('Terminate '+n+'?'))api('kill',{pid}).then(procs)}

/* mouse & keyboard */
function click_(b,d){api('mouse/click',{button:b,double:!!d})}
function key(k){api('keyboard/key',{key:k})}
function typeText(e){const t=$('typed').value;if(!t&&!e)return;api('keyboard/type',{text:t,enter:e});$('typed').value=''}
function touch(el,onmove,ontap){let lx,ly,t0,moved=0,pend={x:0,y:0},busy=false;
  el.addEventListener('touchstart',e=>{const t=e.touches[0];lx=t.clientX;ly=t.clientY;t0=Date.now();moved=0;e.preventDefault()},{passive:false});
  el.addEventListener('touchmove',e=>{const t=e.touches[0];pend.x+=(t.clientX-lx)*1.6;pend.y+=(t.clientY-ly)*1.6;moved+=Math.abs(t.clientX-lx)+Math.abs(t.clientY-ly);lx=t.clientX;ly=t.clientY;e.preventDefault();flush()},{passive:false});
  el.addEventListener('touchend',()=>{if(ontap&&moved<8&&Date.now()-t0<250)ontap()});
  async function flush(){if(busy)return;busy=true;const x=Math.round(pend.x),y=Math.round(pend.y);pend.x-=x;pend.y-=y;
    if(x||y)await onmove(x,y).catch(()=>{});busy=false;if(Math.abs(pend.x)>=1||Math.abs(pend.y)>=1)flush()}}
touch($('pad'),(x,y)=>api('mouse/move',{dx:x,dy:y}),()=>click_('left'));
touch($('scroll'),(x,y)=>api('mouse/scroll',{amount:Math.round(-y/8)}));

/* files & drives */
let cur='';
const fmt=n=>n>1e9?(n/1e9).toFixed(1)+' GB':n>1e6?(n/1e6).toFixed(1)+' MB':n>1e3?Math.round(n/1e3)+' KB':n+' B';
async function loadDrives(){
  try{
    const d=await api('drives');
    if(d.drives&&d.drives.length){
      $('drives').innerHTML=d.drives.map(x=>`
        <button style="flex:initial;padding:6px 12px;font-size:12px" onclick="files('${x.mount.replace(/\\/g,'\\\\')}')">
          💾 <b>${x.mount}</b>${x.free_gb!=null?` <small style="color:var(--mut)">(${x.free_gb} GB)</small>`:''}
        </button>
      `).join('')+`<button style="flex:initial;padding:6px 12px;font-size:12px" onclick="files('')">🏠 Home</button>`;
    }
  }catch(e){}
}
async function files(p){const d=await api('files'+(p?'?path='+encodeURIComponent(p):''));if(d.error)return;cur=d.path;$('fpath').textContent=d.path;
  const rows=(d.parent?[{name:'..',dir:true,up:d.parent}]:[]).concat(d.items);
  $('files').innerHTML='';rows.forEach(f=>{const full=f.up||(d.path.replace(/[\\/]$/,'')+(d.path.includes('\\')?'\\':'/')+f.name);
    const r=document.createElement('div');r.className='proc';
    const s=document.createElement('span');s.textContent=(f.dir?'📁 ':'📄 ')+f.name+(f.dir?'':'  · '+fmt(f.size));s.style.cursor='pointer';s.style.wordBreak='break-all';
    s.onclick=()=>f.dir?files(full):0;r.appendChild(s);
    if(!f.dir){const b=document.createElement('button');b.textContent='⬇';b.onclick=()=>location.href='/api/files/download?path='+encodeURIComponent(full);
      const o=document.createElement('button');o.textContent='▶ Open';o.onclick=()=>api('files/open',{path:full});const w=document.createElement('span');w.append(o,' ',b);r.appendChild(w)}
    $('files').appendChild(r)})}
async function upload(){const fs=$('upf').files;if(!fs.length)return;const fd=new FormData();fd.append('path',cur);for(const f of fs)fd.append('files',f);
  const r=await fetch('/api/files/upload',{method:'POST',body:fd});const d=await r.json();toast(d.error?'⚠ '+d.error:'✓ '+d.msg);$('upf').value='';files(cur)}

/* fleet management */
let fleetData=[];
async function fleetRefresh(){
  $('fleetList').innerHTML='<span style="color:var(--mut);font-size:12px">Checking fleet node statuses…</span>';
  try{
    const d=await api('fleet');
    fleetData=d.fleet||[];
    const count=fleetData.length+' Node'+(fleetData.length===1?'':'s');
    $('fleetCount').textContent=count;
    if($('tabFleetCount')) $('tabFleetCount').textContent=fleetData.length;
    filterFleet();
  }catch(e){
    $('fleetList').innerHTML='<span style="color:var(--mut);font-size:12px">Error loading fleet nodes.</span>';
  }
}
function filterFleet(){
  const q=$('fleetSearch').value.toLowerCase().trim();
  const filtered=fleetData.filter(x=>(x.name||'').toLowerCase().includes(q)||(x.url||'').toLowerCase().includes(q));
  if(!filtered.length){
    $('fleetList').innerHTML='<span style="color:var(--mut);font-size:12px;padding:8px 0">No matching nodes registered in fleet.</span>';
    return;
  }
  $('fleetList').innerHTML=filtered.map(x=>{
    const isLocal=x.local;
    const badge=x.online?'<span class="badge badge-green">ONLINE</span>':'<span class="badge badge-red">OFFLINE</span>';
    const stats=x.online&&x.cpu!=null?`<span style="color:var(--mut);font-size:11px"> · CPU ${x.cpu}% · RAM ${x.ram}%</span>`:'';
    const btn=isLocal?'<span class="badge badge-green">PRIMARY HOST</span>':
      `<span><button class="acc" style="padding:4px 10px;font-size:11px" onclick="window.open('${x.url}','_blank')">🎮 Control</button> <button class="red" style="padding:4px 8px;font-size:11px" onclick="removeFleetNode('${x.id}')">✕</button></span>`;
    return `<div class="proc" style="padding:10px">
      <div><b>${x.name}</b> ${badge} ${stats}<br><small style="color:var(--mut)">${x.url}</small></div>
      ${btn}
    </div>`;
  }).join('');
}
async function addFleetNode(){
  const name=$('fAddName').value.trim();
  const url=$('fAddUrl').value.trim();
  if(!url){toast('Enter PC URL');return}
  const r=await api('fleet/add',{name,url});
  if(r.ok){
    $('fAddName').value='';$('fAddUrl').value='';$('fleetAddBox').style.display='none';
    fleetRefresh();
  }
}
async function removeFleetNode(id){
  if(!confirm('Remove PC from fleet registry?'))return;
  await api('fleet/remove',{id});
  fleetRefresh();
}
async function autoAddDiscovered(){
  const d=await api('discover');
  if(!d.devices||!d.devices.length){toast('No other PCs found on network');return}
  let added=0;
  for(const dev of d.devices){
    const r=await api('fleet/add',{name:dev.name,url:dev.url});
    if(r.ok)added++;
  }
  toast('Added '+added+' device(s) to fleet');
  fleetRefresh();
}
async function broadcastFleet(act){
  if(!confirm('Broadcast "'+act+'" to ALL fleet PCs?'))return;
  const r=await api('fleet/broadcast',{action:act});
  if(r.msg)toast(r.msg);
}

/* device discovery */
async function discover(){
  $('devList').innerHTML='<span style="color:var(--mut)">Scanning subnet for Project-X-Nano nodes…</span>';
  try{
    const d=await api('discover');
    if(!d.devices||!d.devices.length){
      $('devList').innerHTML='<span style="color:var(--mut)">No other Project-X-Nano nodes found on '+d.my_ip+' subnet.</span>';
      return;
    }
    $('devList').innerHTML=d.devices.map(dev=>`
      <div class="proc"><span>💻 <b>${dev.name}</b> <small style="color:var(--mut)">(${dev.ip})</small></span>
      <span><button class="acc" onclick="window.open('${dev.url}','_blank')">🔗 Open</button></span></div>
    `).join('');
  }catch(e){
    $('devList').innerHTML='<span style="color:var(--mut)">Scan finished.</span>';
  }
}

/* hardware & extras */
function setVol(v){api('volume',{level:+v})}
function setBri(v){api('brightness',{level:+v})}
let tapOn=false;
function toggleTap(){tapOn=!tapOn;$('tapB').textContent='🎯 Tap-to-Click: '+(tapOn?'ON':'OFF');$('tapB').classList.toggle('acc',tapOn)}
$('shot').addEventListener('click',e=>{if(!tapOn)return;const r=e.target.getBoundingClientRect();
  api('mouse/click_at',{x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height});if(!screenStreaming)setTimeout(shot,700)});
async function clipGet(){const d=await api('clipboard');if(!d.error)$('clip').value=d.text}
function clipSet(){api('clipboard',{text:$('clip').value})}
function clipCopy(){const c=$('clip');c.select();try{navigator.clipboard?navigator.clipboard.writeText(c.value):document.execCommand('copy');toast('✓ Copied to clipboard')}catch(e){document.execCommand('copy')}}
function sound(k){api('sound',{kind:k})}
function speak(){api('speak',{text:$('say').value})}
async function autoGet(){const d=await api('autostart');$('autoB').textContent='🚀 Start with PC: '+(d.enabled?'ON':'OFF')}
async function autoTog(){await api('autostart',{enabled:$('autoB').textContent.endsWith('OFF')});autoGet()}
async function cmds(){const c=await api('commands');$('cmds').innerHTML='';c.forEach(n=>{const b=document.createElement('button');b.textContent=n;
  b.onclick=()=>runCmd(n);$('cmds').appendChild(b)})}
async function runCmd(n){if(!confirm('Run "'+n+'" on the PC?'))return;$('cmdout').textContent='Running…';const d=await api('command',{name:n});$('cmdout').textContent=d.output||d.error||''}
function askNotif(){if(window.isSecureContext&&window.Notification)Notification.requestPermission();else toast('Notifications require HTTPS or ntfy app')}
let lastAlert=null;
async function pollAlerts(){try{const d=await api('alerts?since='+(lastAlert===null?999999999:lastAlert));
  if(lastAlert!==null)d.alerts.forEach(a=>{toast('🔔 '+a.text);if(navigator.vibrate)navigator.vibrate(200);
    if(window.isSecureContext&&window.Notification&&Notification.permission==='granted')new Notification('Remote PC',{body:a.text})});
  lastAlert=d.last;}catch(e){}}

/* terminal */
function termView(s){$('adminB').textContent=s.admin?'🛡 ADMIN CONSOLE':'USER CONSOLE';$('adminB').className=s.admin?'badge badge-green':'badge';
  $('termOff').style.display=s.enabled?'none':'block';
  $('termLocked').style.display=s.enabled&&!s.unlocked?'block':'none';
  $('termOn').style.display=s.enabled&&s.unlocked?'block':'none';
  if(s.cwd)$('tcwd').textContent=s.cwd;
  if(!$('tshell').options.length)s.shells.forEach(x=>$('tshell').add(new Option(x,x)))}
async function termStatus(){try{termView(await api('terminal/status'))}catch(e){}}
async function termUnlock(){const r=await fetch('/api/terminal/unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('tpw').value})});
  const d=await r.json();toast(d.error?'⚠ '+d.error:'✓ '+d.msg);$('tpw').value='';termStatus()}
async function termLock(){await api('terminal/lock',{});termStatus()}
async function termRun(){const c=$('tcmd').value.trim();if(!c)return;const o=$('tout');$('tcmd').value='';
  o.textContent+='> '+c+'\n';o.scrollTop=o.scrollHeight;
  const r=await fetch('/api/terminal/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c,shell:$('tshell').value})});
  const d=await r.json();if(d.error){o.textContent+='⚠ '+d.error+'\n';if(d.locked)termStatus()}
  else{o.textContent+=(d.output||'')+(d.output&&!d.output.endsWith('\n')?'\n':'');if(d.cwd)$('tcwd').textContent=d.cwd}
  o.scrollTop=o.scrollHeight}
$('tcmd').addEventListener('keydown',e=>{if(e.key==='Enter')termRun()});
$('tpw').addEventListener('keydown',e=>{if(e.key==='Enter')termUnlock()});

let extrasOn=false;
async function initExtras(){cmds();termStatus();
  try{const v=await api('volume');if(v.level!=null){$('vol').value=v.level;$('volVal').textContent=v.level+'%'}}catch(e){}
  try{const b=await api('brightness');if(b.level!=null){$('bri').value=b.level;$('briVal').textContent=b.level+'%'}}catch(e){}
  if(!extrasOn){extrasOn=true;pollAlerts();setInterval(()=>{if($('main').style.display!=='none')pollAlerts()},5000)}
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{})}
let started=false;
async function init(){files('');loadDrives();fleetRefresh();discover();initExtras();const a=await api('apps');$('apps').innerHTML=a.map(n=>`<button onclick="api('launch',{name:'${n}'})">${n}</button>`).join('');
  stats();procs();if(!started){started=true;setInterval(()=>{if($('main').style.display!=='none')stats()},4000)}}
$('pw').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
fetch('/api/stats').then(r=>show(r.ok));
</script></body></html>"""


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
    app.run(host=host, port=port, threaded=True)
