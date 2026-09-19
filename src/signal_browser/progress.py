from __future__ import annotations

import os
import shutil
import sys
import time


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _fmt_time(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _progress(label: str, done: int, total: int, start_ts: float) -> None:
    width = shutil.get_terminal_size(fallback=(80, 20)).columns
    barw = max(10, min(40, width - 50))
    pct = int(100 * done / max(1, total))
    fill = int(barw * done / max(1, total))
    filled = "█" * fill
    unfilled = "░" * (barw - fill)

    if _supports_color():
        blue = "\x1b[38;2;59;69;253m"
        reset = "\x1b[0m"
        bar = f"{blue}{filled}{reset}{unfilled}"
    else:
        bar = filled + unfilled

    elapsed = time.time() - start_ts
    rate = (done / elapsed) if elapsed > 0 else 0
    eta = ((total - done) / rate) if rate > 0 and total > 0 else 0
    msg = f"{label} [{bar}] {done}/{total} ({pct}%) | elapsed {_fmt_time(elapsed)} | eta {_fmt_time(eta)}"

    out = "\r" + (msg if _supports_color() else msg[: width - 1])
    sys.stdout.write(out)
    sys.stdout.flush()
