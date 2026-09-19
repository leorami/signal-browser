from __future__ import annotations

import argparse
import threading
import webbrowser

from .server import start_server
from .state import AppState
from .window_prefs import (
    MIN_HEIGHT,
    MIN_WIDTH,
    clamp_window_prefs,
    load_window_prefs,
    save_window_prefs,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="signal-browser", description="Local Signal Browser desktop app")
    parser.add_argument("--serve", action="store_true", help="Open the local site in a browser instead of an app window")
    parser.add_argument("--port", type=int, default=8765, help="Local port (default 8765)")
    # macOS `open App.app` may pass -psn_...; ignore unknown launch args.
    args, _unknown = parser.parse_known_args(argv)

    server, state = start_server(AppState(), host="127.0.0.1", port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={state.token}"

    if args.serve:
        webbrowser.open(url)
        print(url)
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
        return

    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        print("pywebview is not installed; opened the local site in your browser.")
        print(url)
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
        return

    screens = []
    try:
        screens = list(webview.screens)
    except Exception:
        screens = []
    prefs = clamp_window_prefs(load_window_prefs(), screens)
    create_kwargs: dict = {
        "width": prefs["width"],
        "height": prefs["height"],
        "min_size": (MIN_WIDTH, MIN_HEIGHT),
        "text_select": True,
        "maximized": bool(prefs.get("maximized")),
    }
    if prefs.get("x") is not None and prefs.get("y") is not None:
        create_kwargs["x"] = int(prefs["x"])
        create_kwargs["y"] = int(prefs["y"])

    window = webview.create_window("Signal Browser", url, **create_kwargs)
    save_timer: dict[str, threading.Timer | None] = {"t": None}

    def flush(update: dict | None = None) -> None:
        if update:
            prefs.update(update)
        save_window_prefs(prefs)

    def schedule() -> None:
        existing = save_timer["t"]
        if existing:
            existing.cancel()
        timer = threading.Timer(0.25, flush)
        save_timer["t"] = timer
        timer.daemon = True
        timer.start()

    def on_resized(width: int, height: int) -> None:
        if prefs.get("maximized"):
            return
        prefs["width"] = max(MIN_WIDTH, int(width))
        prefs["height"] = max(MIN_HEIGHT, int(height))
        schedule()

    def on_moved(x: int, y: int) -> None:
        if prefs.get("maximized"):
            return
        prefs["x"] = int(x)
        prefs["y"] = int(y)
        schedule()

    def on_maximized() -> None:
        prefs["maximized"] = True
        schedule()

    def on_restored() -> None:
        prefs["maximized"] = False
        schedule()

    def snapshot_from_window() -> None:
        try:
            prefs["width"] = max(MIN_WIDTH, int(window.width))
            prefs["height"] = max(MIN_HEIGHT, int(window.height))
            prefs["x"] = int(window.x)
            prefs["y"] = int(window.y)
        except Exception:
            pass

    def on_closing() -> None:
        existing = save_timer["t"]
        if existing:
            existing.cancel()
        if not prefs.get("maximized"):
            snapshot_from_window()
        flush()

    def on_closed() -> None:
        on_closing()
        state.lock_vault()
        server.shutdown()

    window.events.resized += on_resized
    window.events.moved += on_moved
    window.events.maximized += on_maximized
    window.events.restored += on_restored
    window.events.closing += on_closing
    window.events.closed += on_closed
    webview.start()


if __name__ == "__main__":
    main()
