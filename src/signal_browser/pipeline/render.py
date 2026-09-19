from __future__ import annotations

import datetime as dt
import json
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


def load_asset(name: str) -> str:
    return importlib_resources.files("signal_browser").joinpath("assets", name).read_text(encoding="utf-8")


def inject_brand(html: str) -> str:
    logo = load_asset("logo.svg")
    wordmark = load_asset("wordmark.svg")
    return (
        html
        .replace("<!--__LOGO__-->", logo)
        .replace("<!--__WORDMARK__-->", wordmark)
        .replace("__LOGO_URI__", quote(logo, safe=""))
    )


def render_html(
    threads: list[dict[str, Any]],
    out: str | Path,
    *,
    template: Optional[str | Path] = None,
    css: Optional[str | Path] = None,
    viewer_js: Optional[str | Path] = None,
    exported_on: Optional[str] = None,
) -> Path:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = exported_on or dt.datetime.now().strftime("%a, %b %d, %Y • %I:%M %p")
    if template:
        tpl_text = Path(template).read_text(encoding="utf-8")
    else:
        tpl_text = load_asset("template.html")
    if css:
        css_text = Path(css).read_text(encoding="utf-8")
    else:
        css_text = load_asset("styles.css")
    if viewer_js:
        js_text = Path(viewer_js).read_text(encoding="utf-8")
    else:
        js_text = load_asset("viewer.js")

    payload = json.dumps(threads, ensure_ascii=False)
    html = inject_brand(
        tpl_text
        .replace("__DATA__", payload)
        .replace("__STAMP__", stamp)
        .replace("/*__INLINE_CSS__*/", css_text)
        .replace("/*__VIEWER_JS__*/", js_text)
    )
    dest = out_dir / "index.html"
    dest.write_text(html, encoding="utf-8")
    return dest


def public_thread(thread: dict[str, Any], *, include_messages: bool = True) -> dict[str, Any]:
    item = {
        "id": thread.get("id"),
        "thread": thread.get("thread"),
        "unknown": bool(thread.get("unknown")),
        "group": bool(thread.get("group")),
        "pinned": bool(thread.get("pinned")),
        "avatar": thread.get("avatar") or "",
        "avatarEncrypted": bool(thread.get("avatarEncrypted")),
        "lastTs": thread.get("lastTs") or 0,
        "lastPreview": thread.get("lastPreview") or "",
        "count": len(thread.get("messages") or []),
    }
    if include_messages:
        item["messages"] = thread.get("messages") or []
    return item
