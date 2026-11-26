from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import os
import sys


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_protect(raw: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = _DATA_BLOB(len(raw), buf)
    out_blob = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "MokpoSarangChurchQA",
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("Windows DPAPI CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(enc: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(enc, len(enc))
    in_blob = _DATA_BLOB(len(enc), buf)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("Windows DPAPI CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _fallback_keystream(length: int) -> bytes:
    seed = f"mokpo-sarang-qa|{os.environ.get('COMPUTERNAME', '')}|{os.environ.get('USERNAME', '')}".encode("utf-8")
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_secret(plaintext: str) -> str:
    """Encrypt an API key for local DB storage using Windows DPAPI (with safe fallback)."""
    text = (plaintext or "").strip()
    if not text:
        return ""
    if text.startswith("dpapi:") or text.startswith("obf:"):
        return text
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            protected = _dpapi_protect(raw)
            return "dpapi:" + base64.b64encode(protected).decode("ascii")
        except Exception:
            pass
    ks = _fallback_keystream(len(raw))
    xored = bytes(a ^ b for a, b in zip(raw, ks))
    return "obf:" + base64.b64encode(xored).decode("ascii")


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored API key back to plaintext in memory only."""
    val = (stored or "").strip()
    if not val:
        return ""
    if val.startswith("dpapi:"):
        if sys.platform != "win32":
            return ""
        try:
            enc = base64.b64decode(val[6:].encode("ascii"))
            return _dpapi_unprotect(enc).decode("utf-8")
        except Exception:
            return ""
    if val.startswith("obf:"):
        try:
            enc = base64.b64decode(val[4:].encode("ascii"))
            ks = _fallback_keystream(len(enc))
            return bytes(a ^ b for a, b in zip(enc, ks)).decode("utf-8")
        except Exception:
            return ""
    return val


def mask_secret(plaintext: str) -> str:
    """Return a non-reversible display mask such as 'sk-ant-...9x2a'."""
    s = (plaintext or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "*" * len(s)
    prefix = s[:6] if "-" in s[:8] else s[:4]
    return f"{prefix}...{s[-4:]}"
