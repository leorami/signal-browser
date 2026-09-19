"""PyInstaller/console entry that imports the app as a package."""

from __future__ import annotations

import traceback
from pathlib import Path


def _log_crash(exc: BaseException) -> None:
    try:
        log_dir = Path.home() / "Library" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / "SignalBrowser.log"
        log.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from signal_browser.app.main import main
        main()
    except Exception as exc:
        _log_crash(exc)
        raise
