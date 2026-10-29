# RemotePC

Control your own PC from your phone's browser.

**Features:** power (shutdown / restart / sign out / lock / sleep / hibernate / timers), touchpad + keyboard,
tap-to-click on the live screen, screenshots, clipboard sync, file browser (download / upload / open),
volume + brightness sliders, media keys, "find my PC" alarm, text-to-speech, webcam snapshot,
open sites/apps, saved one-tap commands, process list with "notify me when it closes",
alerts (low battery, new logins, failed logins), start-with-PC, installable on your home screen.

## Setup (on the PC you want to control)

1. Install Python 3.9+ from python.org (tick "Add to PATH").
2. In this folder: `pip install -r requirements.txt` then `python server.py`
3. First run prints a **password** (shown once) and a URL like `http://192.168.1.5:8765`.
4. Open that URL on your phone (same Wi-Fi) and log in. You stay logged in for 7 days.

## Windows .exe

Double-click `build.bat` -> `dist\RemotePC.exe`. Run it once normally to see the password, then turn on
**Start with PC** in the app. Allow **Private networks** if Windows Firewall asks.

## Add to home screen (app-like)

- Android Chrome: menu -> "Add to Home screen". iPhone Safari: Share -> "Add to Home Screen".
- Over plain `http://` it is a shortcut. For a full installable app and browser notifications you need HTTPS:
  install **Tailscale** on PC + phone and run `tailscale serve --bg 8765`; use the https URL it prints.

## Alerts when the page is closed

In `config.json` set `"ntfy_topic": "some-long-random-name"`, install the free **ntfy** app on your phone and
subscribe to the same topic. You'll get: battery low, new login, failed logins, "process finished".

## config.json

- `apps`: buttons under "Open". `commands`: one-tap commands (only these names can ever run).
- `file_roots`: folders the file browser may see (default: your home folder), e.g. `["C:\\Users\\you\\Documents", "D:\\"]`
- `host`: `127.0.0.1` = this PC only. `battery_low`: alert threshold %.
- Reset password: delete `password_hash` from config.json and restart.

## Remote terminal (run any command, optionally as Administrator)

1. On the PC, edit `config.json`: `"terminal_enabled": true`, restart. (It can't be switched on from the web page.)
2. Commands run with the same rights as the server. To get **Administrator**, start it elevated:
   double-click `run-as-admin.bat` (or `build.bat admin` for the exe). Windows asks for one "Yes" click on the PC;
   nobody can approve that prompt remotely. The page shows a green 🛡 ADMIN badge when elevated.
3. In the app: Terminal -> enter your password again -> unlock for 10 minutes. Pick cmd or PowerShell.
4. For admin at every boot: set `"autostart_as_admin": true`, start as admin once, then press "Start with PC".

Safeguards: off by default, password re-entry, only from home Wi-Fi / Tailscale addresses (refused from the
open internet), every command written to `audit.log`, alert on every unlock. Interactive programs (that wait for
typing) are stopped after 60 s. Plain `http://` is unencrypted, so use it only on a network you trust, or over Tailscale.

## Safety

- Use only on a PC you own. Never port-forward to the internet; use Tailscale for outside access.
- The "Clean temp files" example command deletes files; edit or remove it if you don't want it.
- Webcam, clipboard and screen features show everything on your PC to whoever has the password: keep it secret.
- Windows only: media keys, volume slider, start-with-PC (registry), speech. Brightness works on laptops / DDC monitors.
