from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Callable, Optional

from ..crypto.attachments import decrypt_attachment_bytes, looks_encrypted
from ..utils import safe

ICON_MAP = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "pdf": "pdf",
    "zip": "zip",
    "text": "text",
    "word": "doc",
    "excel": "sheet",
    "ppt": "slides",
    "sticker": "sticker",
    "binary": "file",
    "unknown": "file",
}


def icon_for_mime(mtype: str, attachment_type: str = "") -> str:
    if (attachment_type or "").lower() == "sticker":
        return ICON_MAP["sticker"]
    if not mtype:
        return ICON_MAP["unknown"]
    if mtype.startswith("image/"):
        return ICON_MAP["image"]
    if mtype.startswith("video/"):
        return ICON_MAP["video"]
    if mtype.startswith("audio/"):
        return ICON_MAP["audio"]
    if mtype == "application/pdf":
        return ICON_MAP["pdf"]
    if mtype in {"application/zip", "application/x-7z-compressed", "application/x-rar-compressed"}:
        return ICON_MAP["zip"]
    if mtype.startswith("text/"):
        return ICON_MAP["text"]
    if mtype in {"application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        return ICON_MAP["word"]
    if mtype in {"application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
        return ICON_MAP["excel"]
    if mtype in {
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return ICON_MAP["ppt"]
    return ICON_MAP["binary"]


def guess_mime(path: Optional[Path] = None, fallback_name: str = "", data: Optional[bytes] = None) -> str:
    name = path.name if path else fallback_name
    mtype, _ = mimetypes.guess_type(name)
    head = b""
    if data:
        head = data[:16]
    elif path and path.exists():
        try:
            head = path.read_bytes()[:16]
        except Exception:
            head = b""
    if not mtype and head:
        if head.startswith(b"\x89PNG"):
            return "image/png"
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if head.startswith(b"RIFF") and b"WEBP" in head:
            return "image/webp"
        if head.startswith(b"%PDF"):
            return "application/pdf"
        if head.startswith(b"ID3") or head[:2] == b"\xff\xfb":
            return "audio/mpeg"
        if head.startswith(b"OggS"):
            return "audio/ogg"
        if head[4:8] == b"ftyp":
            return "video/mp4"
    return mtype or "application/octet-stream"


def _hash_layout(digest: Optional[str]) -> Optional[str]:
    text = (digest or "").strip()
    if len(text) < 4:
        return None
    return f"{text[:2]}/{text[2:4]}/{text}"


def _candidate_paths(src_root: Path, rel: Optional[str], digest: Optional[str] = None) -> list[Path]:
    found: list[Path] = []

    def add(path: Optional[Path]) -> None:
        if path is None:
            return
        resolved = path if path.is_absolute() else (src_root / path)
        if resolved not in found:
            found.append(resolved)

    if rel:
        raw = Path(rel)
        if raw.is_absolute():
            add(raw)
        add(src_root / rel)
        add(src_root / rel.lstrip("/"))
        name = raw.name
        if name and name != rel:
            add(src_root / name)
    layout = _hash_layout(digest)
    if layout:
        add(src_root / layout)
    if digest:
        add(src_root / digest)
    return found


def _read_src(src_root: Path, rel: Optional[str], digest: Optional[str] = None) -> Optional[bytes]:
    if not rel and not digest:
        return None
    for path in _candidate_paths(src_root, rel, digest):
        if not path.is_file():
            continue
        try:
            return path.read_bytes()
        except Exception:
            continue
    return None


def _try_decrypt(data: bytes, *keys: Optional[str]) -> tuple[bytes, bool]:
    usable = [k for k in keys if k]
    if usable:
        try:
            plain = decrypt_attachment_bytes(data, *usable)
            return plain, looks_encrypted(plain)
        except Exception:
            pass
    return data, looks_encrypted(data)


class MediaSink:
    def store(self, name: str, data: bytes, mime: str) -> str:
        raise NotImplementedError


class DirectorySink(MediaSink):
    def __init__(self, root: Path, prefix: str = "assets"):
        self.root = Path(root)
        self.prefix = prefix
        (self.root / prefix).mkdir(parents=True, exist_ok=True)

    def store(self, name: str, data: bytes, mime: str) -> str:
        dest = self.root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)
        return str(dest.relative_to(self.root))


class MemorySink(MediaSink):
    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.meta: dict[str, dict[str, str]] = {}

    def store(self, name: str, data: bytes, mime: str) -> str:
        blob_id = hashlib.sha1(data).hexdigest()
        self.blobs[blob_id] = data
        self.meta[blob_id] = {"name": Path(name).name, "mime": mime, "size": str(len(data))}
        return f"blob:{blob_id}"


def export_media(
    threads: list[dict[str, Any]],
    src: str | Path,
    sink: MediaSink,
    *,
    progress: Optional[Callable[[str, int, int, float], None]] = None,
) -> MediaSink:
    src_root = Path(src)
    total = sum(1 + len(m.get("atts") or []) for t in threads for m in t.get("messages") or [])
    done = 0
    start = __import__("time").time()
    if progress:
        progress("Media", 0, max(1, total), start)

    for thread in threads:
        fs_name = safe(thread.get("fsName") or thread.get("thread") or "chat")
        info = thread.get("avatarInfo") or {}
        raw = _read_src(src_root, info.get("path"), info.get("hash"))
        if raw:
            data, enc = _try_decrypt(raw, info.get("key1"), info.get("key2"))
            if not enc:
                mime = guess_mime(fallback_name=info.get("path") or "", data=data)
                ext = Path(info.get("path") or "").suffix or mimetypes.guess_extension(mime) or ".bin"
                rel = sink.store(f"assets/avatars/{fs_name}{ext}", data, mime)
                thread["avatar"] = rel
                thread["avatarEncrypted"] = False
            else:
                thread["avatar"] = ""
                thread["avatarEncrypted"] = True
        thread.pop("avatarInfo", None)
        done += 1
        if progress:
            progress("Media", done, max(1, total), start)

        for msg in thread.get("messages") or []:
            exported = []
            for att in msg.get("atts") or []:
                item = _export_one(att, src_root, sink, fs_name)
                if item:
                    exported.append(item)
                done += 1
                if progress:
                    progress("Media", done, max(1, total), start)
            msg["atts"] = exported
            if not msg.get("body") and exported:
                pass
    return sink


def _export_one(att: dict[str, Any], src_root: Path, sink: MediaSink, fs_name: str) -> Optional[dict[str, Any]]:
    rel = att.get("relPath")
    raw = _read_src(src_root, rel)
    if raw is None and att.get("thumbnailPath"):
        raw = _read_src(src_root, att.get("thumbnailPath"))
        rel = att.get("thumbnailPath")
        att["localKey"] = att.get("thumbnailLocalKey") or att.get("localKey")
    if raw is None:
        return None
    data, enc = _try_decrypt(raw, att.get("localKey"), att.get("key_alt"))
    name = safe(att.get("name") or Path(rel or "file").name)
    mime = att.get("contentType") or guess_mime(fallback_name=name, data=data)
    if mime == "application/octet-stream":
        mime = guess_mime(fallback_name=name, data=data)
    digest = hashlib.sha1((rel or name).encode()).hexdigest()[:8]
    stored = sink.store(f"assets/{fs_name}/{digest}_{name}", data, mime)
    thumb_rel = None
    if att.get("thumbnailPath"):
        t_raw = _read_src(src_root, att["thumbnailPath"])
        if t_raw:
            t_data, _ = _try_decrypt(t_raw, att.get("thumbnailLocalKey"), att.get("localKey"))
            t_mime = guess_mime(fallback_name=att["thumbnailPath"], data=t_data)
            thumb_rel = sink.store(f"assets/{fs_name}/thumb_{digest}_{name}", t_data, t_mime)
    poster = None
    if att.get("screenshotPath"):
        s_raw = _read_src(src_root, att["screenshotPath"])
        if s_raw:
            s_data, _ = _try_decrypt(s_raw, att.get("screenshotLocalKey"), att.get("localKey"))
            s_mime = guess_mime(fallback_name=att["screenshotPath"], data=s_data)
            poster = sink.store(f"assets/{fs_name}/poster_{digest}_{name}", s_data, s_mime)
    return {
        "name": att.get("name") or name,
        "path": stored,
        "thumb": thumb_rel,
        "poster": poster,
        "mime": mime,
        "icon": icon_for_mime(mime, att.get("attachmentType") or ""),
        "likelyEncrypted": bool(enc),
        "originalPath": None,
        "contentType": mime,
        "attachmentType": att.get("attachmentType") or "attachment",
        "width": att.get("width"),
        "height": att.get("height"),
        "caption": att.get("caption") or "",
        "duration": att.get("duration"),
    }
