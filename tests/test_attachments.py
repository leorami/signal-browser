from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib
import hmac
import os

from signal_browser.crypto.attachments import decrypt_attachment_bytes, looks_encrypted


def _pkcs7(data: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    return data + bytes([pad]) * pad


def test_decrypt_v2_attachment():
    plaintext = b"hello signal attachment" * 8
    aes_key = os.urandom(32)
    mac_key = os.urandom(32)
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(_pkcs7(plaintext)) + encryptor.finalize()
    mac = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    blob = iv + ct + mac
    import base64
    key = base64.b64encode(aes_key + mac_key).decode()
    assert decrypt_attachment_bytes(blob, key) == plaintext


def test_decrypt_gcm_fallback():
    plaintext = b"gcm-payload"
    key = os.urandom(32)
    nonce = os.urandom(12)
    blob = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
    assert decrypt_attachment_bytes(blob, key.hex()) == plaintext


def test_looks_encrypted_high_entropy():
    assert looks_encrypted(os.urandom(512))
    assert not looks_encrypted(b"\x89PNG\r\n\x1a\n" + b"not-random")
