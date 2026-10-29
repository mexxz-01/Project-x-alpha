import sys
import re
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def rename_brand(new_name):
    clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '', new_name.strip())
    if not clean_name:
        print("[!] Invalid name.")
        sys.exit(1)

    print("=" * 60)
    print(f"       Rebranding Project to: {clean_name}")
    print("=" * 60)

    # 1. Update server.py
    server_py = BASE_DIR / "server.py"
    if server_py.exists():
        content = server_py.read_text(encoding="utf-8")
        content = re.sub(r'<title>.*?</title>', f'<title>{clean_name}</title>', content)
        content = re.sub(r'<span id="host">.*?</span>', f'<span id="host">{clean_name}</span>', content)
        content = re.sub(r'<meta name="apple-mobile-web-app-title" content=".*?">', f'<meta name="apple-mobile-web-app-title" content="{clean_name}">', content)
        content = re.sub(r'<h1 style="font-size:22px;margin:0">.*?</h1>', f'<h1 style="font-size:22px;margin:0">{clean_name}</h1>', content)
        content = re.sub(r'download_name=".*?\.apk"', f'download_name="{clean_name}.apk"', content)
        content = re.sub(r'Scanning subnet for .*? nodes', f'Scanning subnet for {clean_name} nodes', content)
        content = re.sub(r'No other .*? nodes found', f'No other {clean_name} nodes found', content)
        content = re.sub(r'=== .*? running ===', f'=== {clean_name} running ===', content)
        server_py.write_text(content, encoding="utf-8")
        print("[OK] server.py updated.")

    # 2. Update RemotePC.spec
    spec_file = BASE_DIR / "RemotePC.spec"
    if spec_file.exists():
        spec_content = spec_file.read_text(encoding="utf-8")
        spec_content = re.sub(r"name=['\"].*?['\"]", f"name='{clean_name}'", spec_content)
        spec_file.write_text(spec_content, encoding="utf-8")
        print("[OK] RemotePC.spec updated.")

    # 3. Update Android resources
    strings_xml = BASE_DIR / "android" / "res" / "values" / "strings.xml"
    if strings_xml.exists():
        s_content = strings_xml.read_text(encoding="utf-8")
        s_content = re.sub(r'<string name="app_name">.*?</string>', f'<string name="app_name">{clean_name} Controller</string>', s_content)
        strings_xml.write_text(s_content, encoding="utf-8")
        print("[OK] android strings.xml updated.")

    layout_xml = BASE_DIR / "android" / "res" / "layout" / "activity_main.xml"
    if layout_xml.exists():
        l_content = layout_xml.read_text(encoding="utf-8")
        l_content = re.sub(r'android:id="@\+id/txtAppTitle"\s+android:layout_width="0dp"\s+android:layout_height="wrap_content"\s+android:layout_weight="1"\s+android:text=".*?"',
                           f'android:id="@+id/txtAppTitle"\n            android:layout_width="0dp"\n            android:layout_height="wrap_content"\n            android:layout_weight="1"\n            android:text="{clean_name}"', l_content)
        layout_xml.write_text(l_content, encoding="utf-8")
        print("[OK] android activity_main.xml updated.")

    build_apk_py = BASE_DIR / "android" / "build_apk.py"
    if build_apk_py.exists():
        b_content = build_apk_py.read_text(encoding="utf-8")
        b_content = re.sub(r'final_apk = DIST_DIR / ".*?\.apk"', f'final_apk = DIST_DIR / "{clean_name}.apk"', b_content)
        b_content = re.sub(r'ROOT_DIR / ".*?\.apk"', f'ROOT_DIR / "{clean_name}.apk"', b_content)
        build_apk_py.write_text(b_content, encoding="utf-8")
        print("[OK] android build_apk.py updated.")

    # 4. Update setup.ps1
    setup_ps1 = BASE_DIR / "setup.ps1"
    if setup_ps1.exists():
        ps_content = setup_ps1.read_text(encoding="utf-8")
        ps_content = re.sub(r'\$InstallDir = "\$env:LOCALAPPDATA\\.*?"', f'$InstallDir = "$env:LOCALAPPDATA\\\\{clean_name}"', ps_content)
        ps_content = re.sub(r'\$ExePath = Join-Path \$InstallDir ".*?\.exe"', f'$ExePath = Join-Path $InstallDir "{clean_name}.exe"', ps_content)
        ps_content = re.sub(r'\$ApkPath = Join-Path \$InstallDir ".*?\.apk"', f'$ApkPath = Join-Path $InstallDir "{clean_name}.apk"', ps_content)
        ps_content = re.sub(r'Stop-Process -Name .*? -Force', f'Stop-Process -Name {clean_name}, RemotePC, Project-X-Nano -Force', ps_content)
        ps_content = re.sub(r'dist/.*?\.exe', f'dist/{clean_name}.exe', ps_content)
        ps_content = re.sub(r'dist/.*?\.apk', f'dist/{clean_name}.apk', ps_content)
        ps_content = re.sub(r'rule name=".*?"', f'rule name="{clean_name}"', ps_content)
        setup_ps1.write_text(ps_content, encoding="utf-8")
        print("[OK] setup.ps1 updated.")

    # 5. Rebuild Task Manager Windows Executable (.exe)
    print("\n[*] Rebuilding Windows Executable (Task Manager process name)...")
    r = subprocess.run(["pyinstaller", "--noconfirm", "RemotePC.spec"], cwd=BASE_DIR, capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[SUCCESS] Process renamed: dist\\{clean_name}.exe (Shows as '{clean_name}' in Task Manager)")
    else:
        print("[!] PyInstaller build warning:", r.stderr[:300])

    # 6. Rebuild Android APK (.apk)
    print("\n[*] Rebuilding Android APK...")
    r_apk = subprocess.run([sys.executable, str(BASE_DIR / "android" / "build_apk.py")], cwd=BASE_DIR, capture_output=True, text=True)
    if r_apk.returncode == 0:
        print(f"[SUCCESS] Android APK renamed: dist\\{clean_name}.apk")
    else:
        print("[!] Android build warning:", r_apk.stderr[:300])

    print("=" * 60)
    print(f"[COMPLETE] Brand successfully changed to '{clean_name}' everywhere!")
    print(f"Task Manager Process: {clean_name}.exe")
    print(f"Android App:          {clean_name}.apk")
    print(f"Dashboard Title:      {clean_name}")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rename.py <NewName>")
        print("Example: python rename.py RemotePC")
        sys.exit(1)
    rename_brand(sys.argv[1])
