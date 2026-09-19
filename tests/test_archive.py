from pathlib import Path
import pytest
from signal_browser.crypto.archive import Vault, VaultError


def test_vault_roundtrip(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("correct horse battery staple")
    vault.put_blob("abc", b"image-bytes")
    vault.save_catalog({"exportedOn": "now", "threads": [{"thread": "Ada"}], "blobs": {"abc": {"mime": "image/png"}}})
    vault.lock()

    with pytest.raises(VaultError):
        vault.load_catalog()

    vault.unlock("correct horse battery staple")
    catalog = vault.load_catalog()
    assert catalog["threads"][0]["thread"] == "Ada"
    assert vault.get_blob("abc") == b"image-bytes"


def test_vault_wrong_passphrase(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    vault.lock()
    with pytest.raises(VaultError, match="passphrase"):
        vault.unlock("bbbbbbbb")


def test_replace_blobs(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    vault.put_blob("old", b"one")
    vault.replace_blobs({"new": b"two"})
    with pytest.raises(VaultError):
        vault.get_blob("old")
    assert vault.get_blob("new") == b"two"


def test_put_blobs_keeps_existing(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    vault.put_blob("old", b"one")
    vault.put_blobs({"old": b"ignored", "new": b"two"})
    assert vault.get_blob("old") == b"one"
    assert vault.get_blob("new") == b"two"


def test_catalog_snapshots(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    assert vault.list_snapshots() == []

    vault.save_catalog({"exportedOn": "first", "threads": [{"thread": "Ada", "messages": [{"body": "hi"}]}], "blobs": {}})
    vault.save_catalog({"exportedOn": "second", "threads": [{"thread": "Ada", "messages": [{"body": "later"}]}], "blobs": {}})
    snaps = vault.list_snapshots()
    assert len(snaps) == 2
    assert snaps[0]["label"] == "second"
    assert snaps[0]["current"] is True
    assert snaps[1]["label"] == "first"
    assert snaps[1]["current"] is False

    older = vault.load_catalog(snaps[1]["id"])
    latest = vault.load_catalog()
    assert older["threads"][0]["messages"][0]["body"] == "hi"
    assert latest["threads"][0]["messages"][0]["body"] == "later"


def test_ensure_baseline_snapshot(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    vault.save_catalog({"exportedOn": "now", "threads": [{"thread": "Bea", "messages": []}], "blobs": {}}, snapshot=False)
    vault.ensure_baseline_snapshot()
    snaps = vault.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["conversations"] == 1


def test_delete_snapshot_wipes_file_and_orphan_blobs(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    vault.create("aaaaaaaa")
    vault.put_blob("keep", b"shared")
    vault.put_blob("gone", b"only-old")
    vault.save_catalog({
        "exportedOn": "first",
        "threads": [{"thread": "Ada", "messages": [{"body": "hi"}]}],
        "blobs": {"keep": {"mime": "text/plain"}, "gone": {"mime": "text/plain"}},
    })
    vault.save_catalog({
        "exportedOn": "second",
        "threads": [{"thread": "Ada", "messages": [{"body": "later"}]}],
        "blobs": {"keep": {"mime": "text/plain"}},
    })
    snaps = vault.list_snapshots()
    older = snaps[1]["id"]
    latest = snaps[0]["id"]
    result = vault.delete_snapshot(older)
    assert result["id"] == older
    assert result["removedBlobs"] == 1
    assert len(result["snapshots"]) == 1
    assert result["snapshots"][0]["id"] == latest
    with pytest.raises(VaultError):
        vault.load_catalog(older)
    assert vault.get_blob("keep") == b"shared"
    with pytest.raises(VaultError):
        vault.get_blob("gone")
    assert vault.load_catalog()["exportedOn"] == "second"
    vault.delete_snapshot(latest)
    assert vault.list_snapshots() == []
    assert vault.load_catalog()["exportedOn"] == "second"
    with pytest.raises(VaultError):
        vault.delete_snapshot(latest)
