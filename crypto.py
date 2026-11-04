import os
import sys
import json
from pathlib import Path

IS_WIN = sys.platform == "win32"

if IS_WIN:
    try:
        import win32crypt
    except ImportError:
        win32crypt = None
else:
    win32crypt = None

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Fallback machine key if DPAPI is not available
_FALLBACK_KEY_FILE = Path(__file__).parent / ".pxn_key"

def _get_fallback_key() -> bytes:
    if _FALLBACK_KEY_FILE.exists():
        try:
            return _FALLBACK_KEY_FILE.read_bytes()
        except Exception:
            pass
    key = AESGCM.generate_key(bit_length=256)
    try:
        _FALLBACK_KEY_FILE.write_bytes(key)
    except Exception:
        pass
    return key

def encrypt_data(plaintext: bytes) -> bytes:
    """Encrypt bytes using Windows DPAPI (CryptProtectData) or AES-GCM fallback."""
    if IS_WIN and win32crypt:
        try:
            return b"DPAPI:" + win32crypt.CryptProtectData(plaintext, "ProjectXConfig")
        except Exception as e:
            pass
    # AES-GCM fallback
    key = _get_fallback_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return b"AESGCM:" + nonce + ct

def decrypt_data(ciphertext: bytes) -> bytes:
    """Decrypt bytes using DPAPI or AES-GCM."""
    if ciphertext.startswith(b"DPAPI:"):
        raw = ciphertext[6:]
        if IS_WIN and win32crypt:
            _, decrypted = win32crypt.CryptUnprotectData(raw)
            return decrypted
        raise RuntimeError("Encrypted with DPAPI but DPAPI is unavailable on this platform")
    elif ciphertext.startswith(b"AESGCM:"):
        raw = ciphertext[7:]
        nonce = raw[:12]
        ct = raw[12:]
        key = _get_fallback_key()
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None)
    else:
        # Might be unencrypted plaintext
        return ciphertext

def save_encrypted_config(config_dict: dict, file_path: Path):
    """Encrypt and write JSON dictionary to disk."""
    raw_json = json.dumps(config_dict, indent=2).encode("utf-8")
    encrypted = encrypt_data(raw_json)
    file_path.write_bytes(encrypted)

def load_encrypted_config(file_path: Path) -> dict:
    """Read and decrypt config from disk. If plaintext JSON, auto-migrates cleanly."""
    if not file_path.exists():
        return {}
    content = file_path.read_bytes()
    if not content:
        return {}
    try:
        decrypted = decrypt_data(content)
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        # Check if it was plaintext JSON
        try:
            cfg = json.loads(content.decode("utf-8"))
            try:
                save_encrypted_config(cfg, file_path)
            except Exception:
                pass
            return cfg
        except Exception as e:
            print(f"[Crypto] Failed to parse config: {e}")
            return {}
