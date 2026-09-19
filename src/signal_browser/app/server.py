from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from ..crypto.archive import VaultError
from ..pipeline.render import inject_brand, load_asset
from ..pipeline.updater import update_export
from .state import AppState


def _json(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _html_app() -> bytes:
    html = load_asset("app.html")
    html = html.replace("/*__INLINE_CSS__*/", load_asset("styles.css"))
    html = html.replace("/*__VIEWER_JS__*/", load_asset("viewer.js"))
    return inject_brand(html).encode("utf-8")


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _authorized(self) -> bool:
            token = self.headers.get("X-Export-Token") or ""
            if not token:
                parsed = urlparse(self.path)
                token = (parse_qs(parsed.query).get("t") or [""])[0]
            return token == state.token

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                body = _html_app()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authorized():
                _json(self, 401, {"error": "unauthorized"})
                return
            if path == "/api/status":
                _json(self, 200, state.status())
                return
            if path == "/api/conversations":
                try:
                    _json(self, 200, state.conversations())
                except VaultError as exc:
                    _json(self, 401, {"error": str(exc)})
                return
            if path.startswith("/api/thread/"):
                thread_id = unquote(path[len("/api/thread/"):])
                try:
                    _json(self, 200, state.thread(thread_id))
                except VaultError as exc:
                    _json(self, 404, {"error": str(exc)})
                return
            if path == "/api/progress":
                _json(self, 200, state.progress)
                return
            if path == "/api/snapshots":
                try:
                    _json(self, 200, {"snapshots": state.status().get("snapshots") or []})
                except VaultError as exc:
                    _json(self, 401, {"error": str(exc)})
                return
            if path == "/api/search":
                query = (parse_qs(parsed.query).get("q") or [""])[0]
                try:
                    _json(self, 200, state.search(query))
                except VaultError as exc:
                    _json(self, 401, {"error": str(exc)})
                return
            if path.startswith("/media/"):
                blob_id = unquote(path[len("/media/"):].split("?")[0])
                try:
                    data = state.blob(blob_id)
                except VaultError as exc:
                    _json(self, 401, {"error": str(exc)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", state.blob_mime(blob_id))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            _json(self, 404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                _json(self, 401, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                _json(self, 400, {"error": "invalid json"})
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/setup":
                    state.setup(payload.get("passphrase") or "", bool(payload.get("keychain")))
                    _json(self, 200, state.status())
                    return
                if path == "/api/unlock":
                    state.unlock(payload.get("passphrase"), bool(payload.get("keychain")))
                    _json(self, 200, state.status())
                    return
                if path == "/api/lock":
                    state.lock_vault()
                    _json(self, 200, state.status())
                    return
                if path == "/api/snapshot":
                    _json(self, 200, state.view_snapshot(payload.get("id") or ""))
                    return
                if path == "/api/latest":
                    _json(self, 200, state.view_latest())
                    return
                if path == "/api/snapshot/delete":
                    _json(self, 200, state.delete_snapshot(payload.get("id") or ""))
                    return
                if path in ("/api/update", "/api/backup"):
                    if state.updating:
                        _json(self, 409, {"error": "backup already running"})
                        return
                    if not state.vault.is_unlocked():
                        _json(self, 401, {"error": "locked"})
                        return
                    state.updating = True
                    state.set_progress("Starting", 0, 1)

                    def run() -> None:
                        try:
                            update_export(
                                state.vault,
                                progress=lambda label, done, total: state.set_progress(label, done, total),
                            )
                            state.catalog = state.vault.load_catalog()
                            state.viewing_snapshot = ""
                            state.set_progress("Done", 1, 1)
                        except Exception as exc:
                            state.set_progress("Failed", 0, 1, error=str(exc))
                        finally:
                            state.updating = False

                    threading.Thread(target=run, daemon=True).start()
                    # Wait until finished so the UI's await can complete.
                    while state.updating:
                        threading.Event().wait(0.1)
                    if state.progress.get("error"):
                        _json(self, 500, {"error": state.progress["error"]})
                    else:
                        _json(self, 200, {"ok": True, **state.conversations()})
                    return
                _json(self, 404, {"error": "not found"})
            except VaultError as exc:
                _json(self, 400, {"error": str(exc)})
            except Exception as exc:
                _json(self, 500, {"error": str(exc)})

    return Handler


def start_server(state: Optional[AppState] = None, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, AppState]:
    state = state or AppState()
    if not state.token:
        state.token = secrets.token_urlsafe(24)
    try:
        server = ThreadingHTTPServer((host, port), make_handler(state))
    except OSError:
        if port != 0:
            server = ThreadingHTTPServer((host, 0), make_handler(state))
        else:
            raise
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state
