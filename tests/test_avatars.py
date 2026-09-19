import base64
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from signal_browser.pipeline.media import MemorySink, export_media
from signal_browser.pipeline.normalize import normalize_export, parse_avatar_info

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pkcs7(data: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    return data + bytes([pad]) * pad


def _v2_encrypt(plaintext: bytes) -> tuple[bytes, str]:
    aes_key = os.urandom(32)
    mac_key = os.urandom(32)
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(_pkcs7(plaintext)) + encryptor.finalize()
    mac = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    key = base64.b64encode(aes_key + mac_key).decode()
    return iv + ct + mac, key


def _conv_db(tmp_path: Path, cid: str, name: str, conv_type: str, payload: dict) -> Path:
    db = tmp_path / f"{cid}.sqlite"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, "
        "profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)"
    )
    cur.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, "
        "type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT, json TEXT)"
    )
    cur.execute(
        "INSERT INTO conversations (id, name, type, json) VALUES (?, ?, ?, ?)",
        (cid, name, conv_type, json.dumps(payload)),
    )
    cur.execute(
        "INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) "
        "VALUES (1, ?, 1700000000000, 'incoming', 'Hi', 0)",
        (cid,),
    )
    con.commit()
    con.close()
    return db


def test_parse_desktop_avatar_object():
    info = parse_avatar_info({
        "avatar": {"path": "ab/cd/face", "localKey": "key-one", "hash": "abcdrest", "version": 2},
    })
    assert info["path"] == "ab/cd/face"
    assert info["key1"] == "key-one"
    assert info["hash"] == "abcdrest"


def test_parse_hash_only_and_legacy_string():
    hashed = parse_avatar_info({"avatar": {"hash": "abcdrestofhash", "localKey": "k"}})
    assert hashed["path"] == "ab/cd/abcdrestofhash"
    assert hashed["hash"] == "abcdrestofhash"
    legacy = parse_avatar_info({"profileAvatarPath": "old/avatar.jpg"})
    assert legacy["path"] == "old/avatar.jpg"
    empty = parse_avatar_info({"name": "Ada"})
    assert empty == {}


def test_normalize_contact_avatar_object(tmp_path: Path):
    db = _conv_db(tmp_path, "c1", "Ada", "private", {
        "avatar": {"path": "aa/bb/pic", "localKey": "desk-key", "hash": "aabbhash"},
    })
    threads = normalize_export(db)
    info = threads[0]["avatarInfo"]
    assert info["path"] == "aa/bb/pic"
    assert info["key1"] == "desk-key"
    assert info["hash"] == "aabbhash"


def test_normalize_group_avatar_and_legacy_path(tmp_path: Path):
    group = _conv_db(tmp_path, "g1", "Book Club", "group", {
        "avatar": {"path": "11/22/group", "localKey": "g-key"},
    })
    legacy = _conv_db(tmp_path, "c2", "Bea", "private", {
        "profileAvatarPath": "legacy/bea.jpg",
    })
    g_threads = normalize_export(group)
    l_threads = normalize_export(legacy)
    assert g_threads[0]["group"] is True
    assert g_threads[0]["avatarInfo"]["path"] == "11/22/group"
    assert l_threads[0]["avatarInfo"]["path"] == "legacy/bea.jpg"


def test_export_decrypts_v2_avatar_to_blob(tmp_path: Path):
    blob, key = _v2_encrypt(TINY_PNG)
    src = tmp_path / "attachments"
    dest = src / "aa" / "bb"
    dest.mkdir(parents=True)
    (dest / "pic").write_bytes(blob)
    threads = [{
        "thread": "Ada",
        "fsName": "Ada",
        "avatar": "",
        "avatarEncrypted": False,
        "avatarInfo": {"path": "aa/bb/pic", "key1": key, "key2": None, "hash": None},
        "messages": [],
    }]
    sink = export_media(threads, src, MemorySink())
    assert threads[0]["avatarEncrypted"] is False
    assert threads[0]["avatar"].startswith("blob:")
    blob_id = threads[0]["avatar"].split(":", 1)[1]
    assert sink.blobs[blob_id].startswith(b"\x89PNG")


def test_export_hash_only_layout(tmp_path: Path):
    digest = "abcdrestofhash"
    src = tmp_path / "attachments"
    dest = src / "ab" / "cd"
    dest.mkdir(parents=True)
    (dest / digest).write_bytes(TINY_PNG)
    threads = [{
        "thread": "Ada",
        "fsName": "Ada",
        "avatarInfo": {"path": None, "key1": None, "key2": None, "hash": digest},
        "messages": [],
    }]
    export_media(threads, src, MemorySink())
    assert threads[0]["avatar"].startswith("blob:")
    assert threads[0]["avatarEncrypted"] is False


def test_export_missing_avatar_is_safe(tmp_path: Path):
    threads = [{
        "thread": "Ada",
        "fsName": "Ada",
        "avatar": "",
        "avatarEncrypted": False,
        "avatarInfo": {"path": "no/such/file", "key1": "x", "key2": None, "hash": None},
        "messages": [],
    }]
    export_media(threads, tmp_path / "attachments", MemorySink())
    assert threads[0]["avatar"] == ""
    assert threads[0]["avatarEncrypted"] is False
    assert "avatarInfo" not in threads[0]
