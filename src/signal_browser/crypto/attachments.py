from __future__ import annotations

import base64
import hashlib
import hmac
import math
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def b64_or_hex_to_bytes(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    text = value.strip()
    hexish = len(text) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in text)
    if hexish:
        try:
            return bytes.fromhex(text)
        except Exception:
            pass
    try:
        for pad in ("", "=", "=="):
            try:
                out = base64.b64decode(text + pad, validate=False)
                if out:
                    return out
            except Exception:
                pass
    except Exception:
        pass
    return None


def byte_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    hist = [0] * 256
    for item in data:
        hist[item] += 1
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in hist if count)


def looks_encrypted(data: bytes) -> bool:
    if not data:
        return False
    if data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"%PDF", b"RIFF", b"ftyp", b"OggS", b"ID3")):
        return False
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return False
    if data[:4] == b"\x00\x00\x00" and len(data) > 8:
        return False
    return byte_entropy(data[:4096]) > 7.4


def _unpad_pkcs7(plaintext: bytes) -> bytes:
    if not plaintext:
        return plaintext
    pad = plaintext[-1]
    if 1 <= pad <= 16 and plaintext.endswith(bytes([pad]) * pad):
        return plaintext[:-pad]
    return plaintext


def decrypt_v2_cbc_hmac(data: bytes, key_material: bytes) -> bytes:
    if len(data) < 16 + 32 + 16:
        raise ValueError("attachment too small for v2 layout")
    if len(key_material) < 64:
        raise ValueError("v2 localKey must be 64 bytes")
    aes_key = key_material[:32]
    mac_key = key_material[32:64]
    iv = data[:16]
    mac = data[-32:]
    ciphertext = data[16:-32]
    expected = hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("attachment HMAC mismatch")
    decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return _unpad_pkcs7(plaintext)


def decrypt_gcm(data: bytes, key32: bytes) -> bytes:
    if len(data) < 28:
        raise ValueError("attachment too small for GCM")
    nonce = data[:12]
    return AESGCM(key32[:32]).decrypt(nonce, data[12:], None)


def decrypt_cbc_only(data: bytes, key32: bytes) -> bytes:
    if len(data) < 32:
        raise ValueError("attachment too small for CBC")
    iv = data[:16]
    ciphertext = data[16:]
    decryptor = Cipher(algorithms.AES(key32[:32]), modes.CBC(iv)).decryptor()
    return _unpad_pkcs7(decryptor.update(ciphertext) + decryptor.finalize())


def decrypt_attachment_bytes(data: bytes, *keys: Optional[str]) -> bytes:
    """Decrypt a Signal Desktop attachment using available key material.

    Tries current v2 (AES-256-CBC + HMAC-SHA256) first, then GCM and raw CBC.
    """
    if not data:
        raise ValueError("empty attachment")
    errors: list[str] = []
    for raw in keys:
        material = b64_or_hex_to_bytes(raw)
        if not material:
            continue
        if len(material) >= 64:
            try:
                return decrypt_v2_cbc_hmac(data, material[:64])
            except Exception as exc:
                errors.append(f"v2: {exc}")
        if len(material) >= 32:
            try:
                return decrypt_gcm(data, material[:32])
            except Exception as exc:
                errors.append(f"gcm: {exc}")
            try:
                return decrypt_cbc_only(data, material[:32])
            except Exception as exc:
                errors.append(f"cbc: {exc}")
    raise ValueError("could not decrypt attachment" + (f" ({'; '.join(errors)})" if errors else ""))
