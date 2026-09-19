from __future__ import annotations

import threading
import time
from typing import Any, Optional

from ..crypto.archive import Vault, VaultError
from ..paths import vault_dir
from ..pipeline.render import public_thread

IDLE_LOCK_SECONDS = 15 * 60


class AppState:
    def __init__(self, vault: Optional[Vault] = None):
        self.vault = vault or Vault(vault_dir())
        self.catalog: dict[str, Any] = {"exportedOn": "", "threads": [], "blobs": {}}
        self.token = ""
        self.progress = {"label": "", "done": 0, "total": 1, "error": ""}
        self.last_activity = time.time()
        self.lock = threading.Lock()
        self.updating = False
        self.viewing_snapshot = ""

    def touch(self) -> None:
        self.last_activity = time.time()

    def maybe_autolock(self) -> None:
        if self.vault.is_unlocked() and (time.time() - self.last_activity) > IDLE_LOCK_SECONDS:
            self.lock_vault()

    def status(self) -> dict[str, Any]:
        self.maybe_autolock()
        unlocked = self.vault.is_unlocked()
        snaps = self.vault.list_snapshots() if unlocked and self.vault.exists() else []
        return {
            "hasVault": self.vault.exists(),
            "unlocked": unlocked,
            "keychain": False,
            "keychainAvailable": False,
            "exportedOn": self.catalog.get("exportedOn") if unlocked else "",
            "snapshots": snaps,
            "viewingSnapshot": self.viewing_snapshot if self._is_historical(snaps) else "",
            "historical": self._is_historical(snaps),
        }

    def setup(self, passphrase: str, remember: bool = False) -> None:
        if len(passphrase) < 8:
            raise VaultError("passphrase must be at least 8 characters")
        self.vault.create(passphrase)
        self.catalog = self.vault.load_catalog()
        self.viewing_snapshot = ""
        self.touch()

    def unlock(self, passphrase: Optional[str] = None, use_keychain: bool = False) -> None:
        del use_keychain
        if not passphrase:
            raise VaultError("passphrase required")
        self.vault.unlock(passphrase)
        self.catalog = self.vault.load_catalog()
        self.vault.ensure_baseline_snapshot(self.catalog)
        self.viewing_snapshot = ""
        self.touch()

    def lock_vault(self) -> None:
        self.vault.lock()
        self.catalog = {"exportedOn": "", "threads": [], "blobs": {}}
        self.viewing_snapshot = ""

    def conversations(self) -> dict[str, Any]:
        self._require_unlocked()
        threads = [public_thread(t, include_messages=False) for t in self.catalog.get("threads") or []]
        return {
            "exportedOn": self.catalog.get("exportedOn") or "",
            "threads": threads,
            "viewingSnapshot": self.viewing_snapshot,
            "historical": self._is_historical(),
        }

    def thread(self, thread_id: str) -> dict[str, Any]:
        self._require_unlocked()
        for item in self.catalog.get("threads") or []:
            if str(item.get("id")) == str(thread_id) or item.get("thread") == thread_id:
                return {"thread": public_thread(item, include_messages=True)}
        raise VaultError("conversation not found")

    def view_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        self._require_unlocked()
        sid = (snapshot_id or "").strip()
        if not sid or sid in {"latest", "current"}:
            return self.view_latest()
        self.catalog = self.vault.load_catalog(sid)
        self.viewing_snapshot = sid
        self.touch()
        return self.conversations()

    def view_latest(self) -> dict[str, Any]:
        self._require_unlocked()
        self.catalog = self.vault.load_catalog()
        self.viewing_snapshot = ""
        self.touch()
        return self.conversations()

    def delete_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        self._require_unlocked()
        sid = (snapshot_id or "").strip()
        result = self.vault.delete_snapshot(sid)
        if self.viewing_snapshot == sid:
            self.catalog = self.vault.load_catalog()
            self.viewing_snapshot = ""
        self.touch()
        return {
            **result,
            "exportedOn": self.catalog.get("exportedOn") or "",
            "viewingSnapshot": self.viewing_snapshot,
            "historical": self._is_historical(result.get("snapshots")),
        }

    def search(self, query: str, *, limit: int = 80) -> dict[str, Any]:
        self._require_unlocked()
        needle = (query or "").strip().lower()
        if len(needle) < 2:
            return {"hits": []}
        hits: list[dict[str, Any]] = []
        for thread in self.catalog.get("threads") or []:
            name = thread.get("thread") or ""
            for msg in thread.get("messages") or []:
                if not _message_matches(msg, needle):
                    continue
                hits.append({
                    "threadId": thread.get("id"),
                    "thread": name,
                    "body": msg.get("body") or msg.get("caption") or "",
                    "ts": msg.get("ts") or 0,
                })
                if len(hits) >= limit:
                    return {"hits": hits}
        return {"hits": hits}

    def blob(self, blob_id: str) -> bytes:
        self._require_unlocked()
        return self.vault.get_blob(blob_id)

    def blob_mime(self, blob_id: str) -> str:
        meta = (self.catalog.get("blobs") or {}).get(blob_id) or {}
        return meta.get("mime") or "application/octet-stream"

    def set_progress(self, label: str, done: int = 0, total: int = 1, error: str = "") -> None:
        self.progress = {"label": label, "done": done, "total": max(1, total), "error": error}

    def _is_historical(self, snaps: Optional[list[dict[str, Any]]] = None) -> bool:
        viewing = self.viewing_snapshot or ""
        if not viewing or viewing in {"latest", "current"}:
            return False
        items = snaps if snaps is not None else (self.vault.list_snapshots() if self.vault.exists() else [])
        current = next((s.get("id") or "" for s in items if s.get("current")), "")
        return viewing != current

    def _require_unlocked(self) -> None:
        self.maybe_autolock()
        if not self.vault.is_unlocked():
            raise VaultError("locked")
        self.touch()


def _message_matches(msg: dict[str, Any], needle: str) -> bool:
    parts = [msg.get("body") or "", msg.get("caption") or ""]
    quote = msg.get("quote") or {}
    if isinstance(quote, dict):
        parts.append(quote.get("body") or "")
    return needle in " ".join(str(p) for p in parts).lower()
