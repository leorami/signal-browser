from __future__ import annotations

import binascii
import platform
import subprocess
from typing import Optional

SERVICE = "SignalBrowser"
ACCOUNT = "vault-key"

try:
    import keyring
except Exception:  # pragma: no cover - optional at runtime
    keyring = None


def keychain_available() -> bool:
    if keyring is not None:
        return True
    return platform.system().lower() == "darwin"


def save_key(key: bytes) -> None:
    payload = binascii.hexlify(key).decode("ascii")
    if keyring is not None:
        keyring.set_password(SERVICE, ACCOUNT, payload)
        return
    if platform.system().lower() == "darwin":
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                SERVICE,
                "-a",
                ACCOUNT,
                "-w",
                payload,
            ],
            check=True,
            capture_output=True,
        )
        return
    raise RuntimeError("no keychain backend available")


def load_key() -> Optional[bytes]:
    payload = None
    if keyring is not None:
        payload = keyring.get_password(SERVICE, ACCOUNT)
    elif platform.system().lower() == "darwin":
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            payload = proc.stdout.strip()
    if not payload:
        return None
    try:
        return binascii.unhexlify(payload.strip())
    except Exception:
        return None


def delete_key() -> None:
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass
        return
    if platform.system().lower() == "darwin":
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            capture_output=True,
        )
