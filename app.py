"""
WSGI entrypoint for Render / Gunicorn deployment.
Aliases server:app to app:app so both 'gunicorn app:app' and 'gunicorn server:app' work seamlessly.
"""
import os
from server import app, CFG, lan_ip

if __name__ == "__main__":
    port = int(os.environ.get("PORT", CFG.get("port", 8765)))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting RemotePC on http://{lan_ip()}:{port}")
    app.run(host=host, port=port, threaded=True)
