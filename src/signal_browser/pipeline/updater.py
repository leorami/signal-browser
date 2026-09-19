from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from ..crypto.archive import Vault
from ..paths import signal_attachments_dir, signal_data_dir, vault_dir
from .desktop_db import close_signal_desktop, dump_desktop_db
from .media import MemorySink, export_media
from .normalize import normalize_export

ProgressFn = Callable[[str, int, int], None]


def update_export(
    vault: Vault,
    *,
    desktop_dir: Optional[Path] = None,
    attachments_dir: Optional[Path] = None,
    close_signal: bool = True,
    ignore_wal: bool = False,
    progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    """Dump Signal Desktop, normalize, encrypt into the vault, wipe temps."""
    if not vault.is_unlocked():
        raise RuntimeError("vault is locked")

    def report(label: str, done: int = 0, total: int = 1) -> None:
        if progress:
            progress(label, done, total)

    if close_signal:
        report("Closing Signal Desktop")
        close_signal_desktop()

    desktop = Path(desktop_dir) if desktop_dir else signal_data_dir()
    attachments = Path(attachments_dir) if attachments_dir else (
        Path(desktop) / "attachments.noindex" if desktop_dir else signal_attachments_dir()
    )

    tmp = Path(tempfile.mkdtemp(prefix="signal-browser-"))
    try:
        db_path = tmp / "signal_plain.sqlite"
        report("Decrypting Signal database")
        dump_desktop_db(db_path, desktop_dir=desktop if desktop.exists() else None, ignore_wal=ignore_wal, progress=progress)

        def norm_progress(label: str, done: int, total: int, _start: float) -> None:
            report(label, done, total)

        report("Reading conversations")
        threads = normalize_export(db_path, progress=norm_progress)
        sink = MemorySink()
        export_media(threads, attachments if attachments.exists() else tmp, sink, progress=norm_progress)
        stamp = dt.datetime.now().strftime("%a, %b %d, %Y • %I:%M %p")
        catalog = {
            "exportedOn": stamp,
            "threads": threads,
            "blobs": sink.meta,
        }
        report("Encrypting archive")
        vault.put_blobs(sink.blobs)
        vault.save_catalog(catalog, snapshot=True)
        vault.wipe_plaintext_siblings()
        report("Done", 1, 1)
        snaps = vault.list_snapshots()
        return {
            "exportedOn": stamp,
            "conversations": len(threads),
            "blobs": len(sink.blobs),
            "snapshotId": snaps[0]["id"] if snaps else "",
            "snapshots": len(snaps),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def default_vault() -> Vault:
    return Vault(vault_dir())
