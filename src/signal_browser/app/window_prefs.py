from __future__ import annotations

import json
from typing import Any, Optional

from ..paths import window_state_path

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
MIN_WIDTH = 800
MIN_HEIGHT = 560


def load_window_prefs() -> dict[str, Any]:
    path = window_state_path()
    if not path.exists():
        return _defaults()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _defaults()
    if not isinstance(data, dict):
        return _defaults()
    prefs = _defaults()
    for key in ("x", "y", "width", "height"):
        if _is_int(data.get(key)):
            prefs[key] = int(data[key])
    prefs["maximized"] = bool(data.get("maximized"))
    return prefs


def save_window_prefs(prefs: dict[str, Any]) -> None:
    path = window_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "x": prefs.get("x"),
        "y": prefs.get("y"),
        "width": int(prefs.get("width") or DEFAULT_WIDTH),
        "height": int(prefs.get("height") or DEFAULT_HEIGHT),
        "maximized": bool(prefs.get("maximized")),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clamp_window_prefs(prefs: dict[str, Any], screens: Optional[list[Any]] = None) -> dict[str, Any]:
    out = dict(prefs)
    out["width"] = max(MIN_WIDTH, int(out.get("width") or DEFAULT_WIDTH))
    out["height"] = max(MIN_HEIGHT, int(out.get("height") or DEFAULT_HEIGHT))
    if screens:
        bounds = _union_screens(screens)
        if bounds:
            max_w, max_h = bounds[2], bounds[3]
            out["width"] = min(out["width"], max(MIN_WIDTH, max_w))
            out["height"] = min(out["height"], max(MIN_HEIGHT, max_h))
            if _is_int(out.get("x")) and _is_int(out.get("y")):
                if not _intersects_any(int(out["x"]), int(out["y"]), out["width"], out["height"], screens):
                    out["x"] = None
                    out["y"] = None
    return out


def _defaults() -> dict[str, Any]:
    return {
        "x": None,
        "y": None,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "maximized": False,
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _union_screens(screens: list[Any]) -> Optional[tuple[int, int, int, int]]:
    boxes = []
    for screen in screens:
        try:
            boxes.append((int(screen.x), int(screen.y), int(screen.width), int(screen.height)))
        except Exception:
            continue
    if not boxes:
        return None
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[0] + b[2] for b in boxes)
    bottom = max(b[1] + b[3] for b in boxes)
    return left, top, right - left, bottom - top


def _intersects_any(x: int, y: int, width: int, height: int, screens: list[Any]) -> bool:
    for screen in screens:
        try:
            sx, sy, sw, sh = int(screen.x), int(screen.y), int(screen.width), int(screen.height)
        except Exception:
            continue
        if x + width > sx and x < sx + sw and y + height > sy and y < sy + sh:
            return True
    return False
