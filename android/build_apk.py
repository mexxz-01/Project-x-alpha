import os
import sys
import subprocess
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
BIN_DIR = BASE_DIR / "bin"
RES_DIR = BASE_DIR / "res"
SRC_DIR = BASE_DIR / "src"
MANIFEST = BASE_DIR / "AndroidManifest.xml"
KEYSTORE = BASE_DIR / "debug.keystore"
DIST_DIR = ROOT_DIR / "dist"

JDK_BIN = Path(r"C:\Program Files\Microsoft\jdk-21.0.12.101-hotspot\bin")
JAVAC = JDK_BIN / "javac.exe"
KEYTOOL = JDK_BIN / "keytool.exe"

SDK_DIR = Path(r"C:\Users\DELL\AppData\Local\Android\Sdk")
BUILD_TOOLS = SDK_DIR / "build-tools" / "35.0.0"
AAPT2 = BUILD_TOOLS / "aapt2.exe"
D8 = BUILD_TOOLS / "d8.bat"
ZIPALIGN = BUILD_TOOLS / "zipalign.exe"
APKSIGNER = BUILD_TOOLS / "apksigner.bat"
ANDROID_JAR = SDK_DIR / "platforms" / "android-35" / "android.jar"

def run(cmd, desc="", is_batch=False):
    print(f"[*] {desc}...")
    sys.stdout.flush()
    if is_batch:
        full_cmd = f'cmd.exe /c "{cmd}"'
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    else:
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[!] Error in {desc}:")
        print("STDOUT:", r.stdout)
        print("STDERR:", r.stderr)
        sys.exit(1)
    if r.stdout.strip():
        print(r.stdout.strip())
    sys.stdout.flush()
    return r

def main():
    print("=" * 60)
    print("       Building RemotePC Android Controller APK")
    print("=" * 60)
    sys.stdout.flush()

    # 1. Directories
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (BIN_DIR / "classes").mkdir(parents=True, exist_ok=True)
    (BIN_DIR / "dex").mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Check keystore
    if not KEYSTORE.exists():
        run([
            str(KEYTOOL), "-genkeypair", "-v",
            "-keystore", str(KEYSTORE),
            "-alias", "androiddebugkey",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-storepass", "android", "-keypass", "android",
            "-dname", "CN=RemotePC,O=RemotePC,C=US"
        ], "Generating debug keystore")
    else:
        print("[OK] Keystore found.")

    # 3. Compile resources with aapt2
    compiled_res = BIN_DIR / "compiled_res.zip"
    run([
        str(AAPT2), "compile", "--dir", str(RES_DIR),
        "-o", str(compiled_res)
    ], "Compiling resources with aapt2")

    # 4. Link resources and generate R.java
    initial_apk = BIN_DIR / "app-initial.apk"
    if initial_apk.exists():
        initial_apk.unlink()
    run([
        str(AAPT2), "link",
        "-I", str(ANDROID_JAR),
        str(compiled_res),
        "--manifest", str(MANIFEST),
        "--java", str(SRC_DIR),
        "-o", str(initial_apk),
        "--auto-add-overlay"
    ], "Linking resources & generating R.java")

    # 5. Compile Java sources
    java_files = list(SRC_DIR.rglob("*.java"))
    print(f"[*] Compiling {len(java_files)} Java files...")
    classes_dir = BIN_DIR / "classes"
    run([
        str(JAVAC),
        "-source", "8", "-target", "8",
        "-bootclasspath", str(ANDROID_JAR),
        "-cp", str(ANDROID_JAR),
        "-d", str(classes_dir),
        *[str(f) for f in java_files]
    ], "Compiling Java sources with javac")

    # 6. Convert classes to dex with d8
    class_files = list(classes_dir.rglob("*.class"))
    print(f"[*] Dexing {len(class_files)} .class files...")
    dex_dir = BIN_DIR / "dex"
    dex_file = dex_dir / "classes.dex"
    if dex_file.exists():
        dex_file.unlink()

    d8_cmd = f'"{D8}" --release --min-api 24 --lib "{ANDROID_JAR}" --output "{dex_dir}" ' + ' '.join(f'"{f}"' for f in class_files)
    run(d8_cmd, "Converting to DEX with d8", is_batch=True)

    if not dex_file.exists():
        print("[!] classes.dex was not created!")
        sys.exit(1)

    # 7. Inject classes.dex into APK
    print("[*] Packaging classes.dex into APK...")
    with zipfile.ZipFile(initial_apk, "a") as z:
        z.write(dex_file, "classes.dex")

    # 8. Zipalign APK
    aligned_apk = BIN_DIR / "app-aligned.apk"
    if aligned_apk.exists():
        aligned_apk.unlink()
    run([
        str(ZIPALIGN), "-p", "-f", "4",
        str(initial_apk), str(aligned_apk)
    ], "Zipalign APK")

    # 9. Sign APK with apksigner
    final_apk = DIST_DIR / "RemotePC-Controller.apk"
    if final_apk.exists():
        final_apk.unlink()

    sign_cmd = f'"{APKSIGNER}" sign --ks "{KEYSTORE}" --ks-pass pass:android --key-pass pass:android --ks-key-alias androiddebugkey --out "{final_apk}" "{aligned_apk}"'
    run(sign_cmd, "Signing APK with apksigner", is_batch=True)

    # 10. Copy to root directory
    apk_size_mb = final_apk.stat().st_size / (1024 * 1024)
    shutil.copy2(final_apk, ROOT_DIR / "RemotePC-Controller.apk")

    print("=" * 60)
    print("[SUCCESS] RemotePC Android Controller APK Built Successfully!")
    print(f"Output File: {final_apk}")
    print(f"Root Copy:   {ROOT_DIR / 'RemotePC-Controller.apk'}")
    print(f"Size:        {apk_size_mb:.2f} MB")
    print("=" * 60)

if __name__ == "__main__":
    main()
