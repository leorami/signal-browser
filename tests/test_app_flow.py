from pathlib import Path
from urllib.request import Request, urlopen

from signal_browser.app.server import start_server
from signal_browser.app.state import AppState
from signal_browser.crypto.archive import Vault
from signal_browser.pipeline.desktop_db import describe_providers
from signal_browser.pipeline.updater import update_export


def _req(url: str, token: str, path: str, payload: dict | None = None) -> dict:
    import json
    data = None if payload is None else json.dumps(payload).encode()
    method = "GET" if payload is None else "POST"
    req = Request(url + path, data=data, method=method, headers={"X-Export-Token": token, "Content-Type": "application/json"})
    with urlopen(req) as res:
        return json.loads(res.read().decode())


def test_setup_unlock_lock_and_media(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNAL_BROWSER_HOME", str(tmp_path / "home"))
    state = AppState(Vault(tmp_path / "vault"))
    server, state = start_server(state, port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status = _req(url, state.token, "/api/status")
        assert status["hasVault"] is False
        _req(url, state.token, "/api/setup", {"passphrase": "abcdefgh", "keychain": False})
        state.vault.put_blob("pic", b"hello-img")
        state.catalog = {"exportedOn": "today", "threads": [{"id": "1", "thread": "Ada", "messages": [], "lastPreview": "Hi"}], "blobs": {"pic": {"mime": "image/png"}}}
        state.vault.save_catalog(state.catalog)
        convos = _req(url, state.token, "/api/conversations")
        assert convos["threads"][0]["thread"] == "Ada"
        req = Request(url + "/media/pic", headers={"X-Export-Token": state.token})
        with urlopen(req) as res:
            assert res.read() == b"hello-img"
        _req(url, state.token, "/api/lock", {})
        status = _req(url, state.token, "/api/status")
        assert status["unlocked"] is False
    finally:
        server.shutdown()


def test_update_export_uses_injected_dump(tmp_path, monkeypatch, tiny_db):
    monkeypatch.setenv("SIGNAL_BROWSER_HOME", str(tmp_path / "home"))
    src = tmp_path / "attachments"
    src.mkdir()
    vault = Vault(tmp_path / "vault")
    vault.create("abcdefgh")

    def fake_dump(dest, **kwargs):
        dest = Path(dest)
        dest.write_bytes(Path(tiny_db).read_bytes())
        return dest

    monkeypatch.setattr("signal_browser.pipeline.updater.dump_desktop_db", fake_dump)
    monkeypatch.setattr("signal_browser.pipeline.updater.close_signal_desktop", lambda: True)
    monkeypatch.setattr("signal_browser.pipeline.updater.signal_attachments_dir", lambda: src)
    monkeypatch.setattr("signal_browser.pipeline.updater.signal_data_dir", lambda: tmp_path)
    result = update_export(vault, attachments_dir=src, desktop_dir=tmp_path, close_signal=False)
    assert result["conversations"] >= 1
    catalog = vault.load_catalog()
    assert catalog["threads"][0]["thread"] == "Alice"


def test_describe_providers_keys():
    info = describe_providers()
    assert "signalbackup-tools" in info
    assert "sigtop" in info


def test_backup_snapshots_and_search(tmp_path, monkeypatch, tiny_db):
    monkeypatch.setenv("SIGNAL_BROWSER_HOME", str(tmp_path / "home"))
    src = tmp_path / "attachments"
    src.mkdir()
    state = AppState(Vault(tmp_path / "vault"))
    state.setup("abcdefgh")

    def fake_dump(dest, **kwargs):
        dest = Path(dest)
        dest.write_bytes(Path(tiny_db).read_bytes())
        return dest

    monkeypatch.setattr("signal_browser.pipeline.updater.dump_desktop_db", fake_dump)
    monkeypatch.setattr("signal_browser.pipeline.updater.close_signal_desktop", lambda: True)
    monkeypatch.setattr("signal_browser.pipeline.updater.signal_attachments_dir", lambda: src)
    monkeypatch.setattr("signal_browser.pipeline.updater.signal_data_dir", lambda: tmp_path)

    first = update_export(state.vault, attachments_dir=src, desktop_dir=tmp_path, close_signal=False)
    state.catalog = state.vault.load_catalog()
    assert first["snapshots"] == 1
    hits = state.search("hello")
    assert any((h.get("body") or "") == "Hello" for h in hits["hits"])

    older_id = state.vault.list_snapshots()[0]["id"]
    second = update_export(state.vault, attachments_dir=src, desktop_dir=tmp_path, close_signal=False)
    assert second["snapshots"] == 2
    state.catalog = state.vault.load_catalog()

    server, state = start_server(state, port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        snaps = _req(url, state.token, "/api/snapshots")
        assert len(snaps["snapshots"]) == 2
        viewed = _req(url, state.token, "/api/snapshot", {"id": older_id})
        assert viewed["historical"] is True
        found = _req(url, state.token, "/api/search?q=hello")
        assert found["hits"]
        latest = _req(url, state.token, "/api/latest", {})
        assert latest["historical"] is False
        _req(url, state.token, "/api/snapshot", {"id": older_id})
        deleted = _req(url, state.token, "/api/snapshot/delete", {"id": older_id})
        assert deleted["id"] == older_id
        assert len(deleted["snapshots"]) == 1
        assert deleted["historical"] is False
        remaining = _req(url, state.token, "/api/snapshots")
        assert all(item["id"] != older_id for item in remaining["snapshots"])
    finally:
        server.shutdown()
