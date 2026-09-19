from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = "SIGNALBROWSER"
VERSION = 1
HEADER_NAME = "header.json"
CATALOG_NAME = "catalog.enc"
BLOBS_DIR = "blobs"
SNAPSHOTS_DIR = "snapshots"


class VaultError(Exception):
    pass


def _scrypt_params() -> dict[str, int]:
    return {"n": 2**14, "r": 8, "p": 1, "length": 32}


def derive_key(passphrase: str, salt: bytes, *, n: int = 2**14, r: int = 8, p: int = 1) -> bytes:
    if not passphrase:
        raise VaultError("passphrase is required")
    kdf = Scrypt(salt=salt, length=32, n=n, r=r, p=p)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_bytes(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_bytes(key: bytes, blob: bytes) -> bytes:
    if len(blob) < 13:
        raise VaultError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except Exception as exc:
        raise VaultError("unlock failed") from exc


class Vault:
    """Passphrase-encrypted on-disk archive for catalog JSON and media blobs."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.header_path = self.root / HEADER_NAME
        self.catalog_path = self.root / CATALOG_NAME
        self.blobs_path = self.root / BLOBS_DIR
        self.snapshots_path = self.root / SNAPSHOTS_DIR
        self.key: Optional[bytes] = None
        self.header: dict[str, Any] = {}

    def exists(self) -> bool:
        return self.header_path.exists() and self.catalog_path.exists()

    def create(self, passphrase: str) -> bytes:
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs_path.mkdir(parents=True, exist_ok=True)
        self.snapshots_path.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        params = _scrypt_params()
        key = derive_key(passphrase, salt, n=params["n"], r=params["r"], p=params["p"])
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.header = {
            "magic": MAGIC,
            "version": VERSION,
            "kdf": "scrypt",
            "salt": salt.hex(),
            "n": params["n"],
            "r": params["r"],
            "p": params["p"],
            "created": now,
            "updated": now,
            "snapshots": [],
            "currentSnapshot": "",
        }
        self.header_path.write_text(json.dumps(self.header, indent=2), encoding="utf-8")
        self.key = key
        self.save_catalog({"exportedOn": "", "threads": [], "blobs": {}}, snapshot=False)
        return key

    def unlock(self, passphrase: str) -> bytes:
        try:
            key = self.key_from_passphrase(passphrase)
            self.unlock_with_key(key)
            return key
        except VaultError as exc:
            text = str(exc).lower()
            if "unlock failed" in text or "ciphertext" in text:
                raise VaultError("That passphrase doesn’t match. Try again.") from exc
            raise

    def key_from_passphrase(self, passphrase: str) -> bytes:
        header = self._read_header()
        salt = bytes.fromhex(header["salt"])
        return derive_key(passphrase, salt, n=int(header["n"]), r=int(header["r"]), p=int(header["p"]))

    def unlock_with_key(self, key: bytes) -> None:
        self.key = key
        # Validate by decrypting the catalog.
        self.load_catalog()

    def lock(self) -> None:
        self.key = None

    def is_unlocked(self) -> bool:
        return self.key is not None

    def save_catalog(self, catalog: dict[str, Any], *, snapshot: bool = True) -> None:
        self._require_key()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        header = self._read_header()
        header["updated"] = now
        blob = encrypt_bytes(self.key, json.dumps(catalog, separators=(",", ":")).encode("utf-8"))
        self.catalog_path.write_bytes(blob)
        if snapshot:
            sid = _snapshot_id()
            self.snapshots_path.mkdir(parents=True, exist_ok=True)
            (self.snapshots_path / f"{sid}.enc").write_bytes(blob)
            snaps = list(header.get("snapshots") or [])
            snaps.append({
                "id": sid,
                "label": catalog.get("exportedOn") or now,
                "created": now,
                "conversations": len(catalog.get("threads") or []),
                "messages": sum(len(t.get("messages") or []) for t in catalog.get("threads") or []),
            })
            header["snapshots"] = snaps
            header["currentSnapshot"] = sid
        self.header = header
        self.header_path.write_text(json.dumps(header, indent=2), encoding="utf-8")

    def load_catalog(self, snapshot_id: Optional[str] = None) -> dict[str, Any]:
        self._require_key()
        path = self._catalog_path_for(snapshot_id)
        if not path.exists():
            if snapshot_id and snapshot_id not in ("latest", "current", ""):
                raise VaultError(f"missing snapshot {snapshot_id}")
            return {"exportedOn": "", "threads": [], "blobs": {}}
        raw = decrypt_bytes(self.key, path.read_bytes())
        return json.loads(raw.decode("utf-8"))

    def list_snapshots(self) -> list[dict[str, Any]]:
        header = self._read_header()
        items = [dict(item) for item in (header.get("snapshots") or [])]
        current = header.get("currentSnapshot") or (items[-1]["id"] if items else "")
        out = []
        for item in reversed(items):
            row = dict(item)
            row["current"] = bool(current) and row.get("id") == current
            out.append(row)
        return out

    def ensure_baseline_snapshot(self, catalog: Optional[dict[str, Any]] = None) -> None:
        """Give pre-snapshot vaults a recoverable first point-in-time copy."""
        header = self._read_header()
        if header.get("snapshots"):
            return
        catalog = catalog if catalog is not None else self.load_catalog()
        if catalog.get("threads"):
            self.save_catalog(catalog, snapshot=True)

    def delete_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Permanently remove a snapshot catalog and unreferenced media."""
        self._require_key()
        sid = (snapshot_id or "").strip()
        if not sid or sid in {"latest", "current"}:
            raise VaultError("choose a specific backup to delete")
        header = self._read_header()
        snaps = [dict(item) for item in (header.get("snapshots") or [])]
        if not any(item.get("id") == sid for item in snaps):
            raise VaultError("backup not found")
        _secure_unlink(self.snapshots_path / f"{sid}.enc")
        header["snapshots"] = [item for item in snaps if item.get("id") != sid]
        if header.get("currentSnapshot") == sid:
            header["currentSnapshot"] = ""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        header["updated"] = now
        self.header = header
        self.header_path.write_text(json.dumps(header, indent=2), encoding="utf-8")
        removed = self._gc_unreferenced_blobs()
        return {"id": sid, "removedBlobs": removed, "snapshots": self.list_snapshots()}

    def _gc_unreferenced_blobs(self) -> int:
        keep = set(_blob_ids(self.load_catalog()))
        for item in self._read_header().get("snapshots") or []:
            sid = item.get("id") or ""
            path = self.snapshots_path / f"{sid}.enc"
            if not sid or not path.exists():
                continue
            try:
                catalog = json.loads(decrypt_bytes(self.key, path.read_bytes()).decode("utf-8"))
            except VaultError:
                continue
            keep.update(_blob_ids(catalog))
        removed = 0
        if not self.blobs_path.exists():
            return 0
        for path in list(self.blobs_path.glob("*.enc")):
            blob_id = path.stem
            if blob_id in keep:
                continue
            _secure_unlink(path)
            removed += 1
        return removed

    def put_blob(self, blob_id: str, data: bytes) -> str:
        self._require_key()
        self.blobs_path.mkdir(parents=True, exist_ok=True)
        path = self.blobs_path / f"{blob_id}.enc"
        if not path.exists():
            path.write_bytes(encrypt_bytes(self.key, data))
        return blob_id

    def put_blobs(self, blobs: dict[str, bytes]) -> None:
        for blob_id, data in blobs.items():
            self.put_blob(blob_id, data)

    def get_blob(self, blob_id: str) -> bytes:
        self._require_key()
        path = self.blobs_path / f"{blob_id}.enc"
        if not path.exists():
            raise VaultError(f"missing blob {blob_id}")
        return decrypt_bytes(self.key, path.read_bytes())

    def replace_blobs(self, blobs: dict[str, bytes]) -> None:
        """Atomically replace media after writing to a sibling temp folder."""
        self._require_key()
        staging = self.root / f".blobs-{os.getpid()}"
        if staging.exists():
            _rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        for blob_id, data in blobs.items():
            (staging / f"{blob_id}.enc").write_bytes(encrypt_bytes(self.key, data))
        if self.blobs_path.exists():
            old = self.root / f".blobs-old-{os.getpid()}"
            self.blobs_path.rename(old)
            staging.rename(self.blobs_path)
            _rmtree(old)
        else:
            staging.rename(self.blobs_path)

    def wipe_plaintext_siblings(self) -> None:
        for name in ("plain.sqlite", "tmp"):
            path = self.root / name
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                _rmtree(path)

    def _catalog_path_for(self, snapshot_id: Optional[str]) -> Path:
        if not snapshot_id or snapshot_id in ("latest", "current"):
            return self.catalog_path
        return self.snapshots_path / f"{snapshot_id}.enc"

    def _read_header(self) -> dict[str, Any]:
        if not self.header_path.exists():
            raise VaultError("no export vault found")
        header = json.loads(self.header_path.read_text(encoding="utf-8"))
        if header.get("magic") != MAGIC:
            raise VaultError("not a Signal Browser vault")
        if int(header.get("version", 0)) != VERSION:
            raise VaultError("unsupported vault version")
        return header

    def _require_key(self) -> None:
        if not self.key:
            raise VaultError("vault is locked")


def _snapshot_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    nanos = time.time_ns() % 1_000_000
    return f"{stamp}{nanos:06d}Z"


def _blob_ids(catalog: dict[str, Any]) -> set[str]:
    return {str(key) for key in (catalog.get("blobs") or {})}


def _secure_unlink(path: Path) -> None:
    """Overwrite a file with random bytes, then unlink it."""
    if path.is_symlink():
        path.unlink()
        return
    if not path.is_file():
        return
    size = path.stat().st_size
    try:
        with open(path, "r+b", buffering=0) as fh:
            remaining = size
            while remaining:
                chunk = min(remaining, 1024 * 1024)
                fh.write(os.urandom(chunk))
                remaining -= chunk
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    path.unlink()


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    if path.exists():
        path.rmdir()
