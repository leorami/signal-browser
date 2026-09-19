from __future__ import annotations

from pathlib import Path
from typing import Optional

from .pipeline.media import DirectorySink, export_media, guess_mime, icon_for_mime
from .pipeline.normalize import normalize_export, parse_avatar_info
from .pipeline.render import render_html
from .progress import _fmt_time, _progress, _supports_color
from .crypto.attachments import (
    b64_or_hex_to_bytes,
    byte_entropy,
    looks_encrypted as _looks_encrypted_bytes,
)


def likely_encrypted_file(path: Path) -> bool:
    try:
        return _looks_encrypted_bytes(path.read_bytes()[:4096])
    except Exception:
        return False


def run_export(
    db: str | Path,
    src: str | Path,
    out: str | Path,
    *,
    template: Optional[str | Path] = None,
    css: Optional[str | Path] = None,
    openssl: Optional[str] = None,
) -> Path:
    """Build a static HTML export. `openssl` is accepted for CLI compatibility."""
    del openssl  # decryption now uses the cryptography package

    def progress(label: str, done: int, total: int, start_ts: float) -> None:
        _progress(label, done, total, start_ts)
        if done >= total:
            import sys
            sys.stdout.write("\n")

    threads = normalize_export(db, progress=progress)
    sink = DirectorySink(Path(out))
    export_media(threads, src, sink, progress=progress)
    return render_html(threads, out, template=template, css=css)


# Back-compat names used by older helpers/tests
ICON_MAP = {
    "image": "🖼️",
    "video": "🎞️",
    "audio": "🎵",
    "pdf": "📄",
    "zip": "🗜️",
    "text": "📄",
    "word": "📝",
    "excel": "📊",
    "ppt": "📽️",
    "binary": "📦",
    "unknown": "📁",
}

_parse_avatar_info_from_json = parse_avatar_info

__all__ = [
    "run_export",
    "icon_for_mime",
    "guess_mime",
    "likely_encrypted_file",
    "b64_or_hex_to_bytes",
    "byte_entropy",
    "_progress",
    "_supports_color",
    "_fmt_time",
]
