"""
RemotePC - Windows System Tray Runner.
Runs RemotePC silently in the background with an icon in the Windows taskbar notification tray.
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path
from PIL import Image, ImageDraw

# Add current dir to path
sys.path.insert(0, str(Path(__file__).parent))
import server

try:
    import pystray
    from pystray import MenuItem as item
except ImportError:
    print("pystray not installed. Run: pip install pystray")
    sys.exit(1)


def create_tray_icon():
    # Draw a stylish PC controller tray icon
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Circle base
    d.ellipse((2, 2, size - 2, size - 2), fill="#1e2230", outline="#3b82f6", width=3)
    # Screen icon
    d.rounded_rectangle([14, 16, 50, 40], radius=4, fill="#3b82f6")
    d.rectangle([28, 40, 36, 46], fill="#3b82f6")
    d.rectangle([22, 46, 42, 49], fill="#3b82f6")
    return img


def open_dashboard(icon, item):
    url = f"http://{server.lan_ip()}:{server.CFG.get('port', 8765)}"
    webbrowser.open(url)


def copy_url(icon, item):
    url = f"http://{server.lan_ip()}:{server.CFG.get('port', 8765)}"
    try:
        import pyperclip
        pyperclip.copy(url)
    except Exception:
        pass


def exit_app(icon, item):
    icon.stop()
    os._exit(0)


def start_server_thread():
    port = int(os.environ.get("PORT", server.CFG.get("port", 8765)))
    host = os.environ.get("HOST", server.CFG.get("host", "0.0.0.0"))
    server.app.run(host=host, port=port, threaded=True, use_reloader=False)


def main():
    # Start Flask server in background thread
    t = threading.Thread(target=start_server_thread, daemon=True)
    t.start()

    url = f"http://{server.lan_ip()}:{server.CFG.get('port', 8765)}"
    menu = pystray.Menu(
        item(f"RemotePC (Port {server.CFG.get('port', 8765)})", None, enabled=False),
        pystray.Menu.SEPARATOR,
        item("🌐 Open Dashboard", open_dashboard, default=True),
        item("📋 Copy URL to Clipboard", copy_url),
        pystray.Menu.SEPARATOR,
        item("🚪 Exit RemotePC", exit_app),
    )

    icon = pystray.Icon("RemotePC", create_tray_icon(), f"RemotePC - {url}", menu)
    icon.run()


if __name__ == "__main__":
    main()
