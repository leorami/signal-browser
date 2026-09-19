import json
import sqlite3
from pathlib import Path
from signal_browser.pipeline.normalize import normalize_export
from signal_browser.pipeline.schema import column_names, table_exists


def test_schema_helpers(tmp_path: Path):
    db = tmp_path / "s.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE conversations (id TEXT, name TEXT)")
    con.commit()
    cur = con.cursor()
    assert table_exists(cur, "conversations")
    assert "name" in column_names(cur, "conversations")
    con.close()


def test_normalize_quotes_reactions_and_preview(tmp_path: Path):
    db = tmp_path / "n.sqlite"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT, isPinned INTEGER)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT, json TEXT)")
    cur.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT, attachmentType TEXT)")
    cur.execute("INSERT INTO conversations (id, name, type, isPinned) VALUES ('1', 'Ada Lovelace', 'private', 1)")
    quote = json.dumps({"quote": {"text": "earlier", "author": "Ada"}, "reactions": [{"emoji": "👍", "fromId": "Ada"}]})
    cur.execute(
        "INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs, json) VALUES (1, '1', 1700000000000, 'incoming', 'Hello there', 0, ?)",
        (quote,),
    )
    cur.execute(
        "INSERT INTO message_attachments (messageId, fileName, path, contentType, attachmentType) VALUES (1, 'pic.jpg', 'aa/bb', 'image/jpeg', 'attachment')"
    )
    con.commit()
    con.close()

    threads = normalize_export(db)
    assert threads[0]["pinned"] is True
    assert threads[0]["thread"] == "Ada Lovelace"
    msg = threads[0]["messages"][0]
    assert msg["quote"]["body"] == "earlier"
    assert msg["reactions"][0]["emoji"] == "👍"
    assert msg["atts"][0]["relPath"] == "aa/bb"
    assert threads[0]["lastPreview"] == "Hello there"


def test_normalize_json_body_and_json_attachments(tmp_path: Path):
    db = tmp_path / "jsonmsgs.sqlite"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT, json TEXT)")
    payload = json.dumps({
        "body": "From json field",
        "attachments": [{"path": "aa/pic", "fileName": "shot.jpg", "contentType": "image/jpeg", "localKey": "abc"}],
    })
    cur.execute("INSERT INTO conversations (id, name, type) VALUES ('c1', 'Ada', 'private')")
    cur.execute(
        "INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs, json) VALUES (1, 'c1', 1700000000000, 'incoming', '', 0, ?)",
        (payload,),
    )
    con.commit()
    con.close()
    threads = normalize_export(db)
    assert threads[0]["messages"][0]["body"] == "From json field"
    assert threads[0]["messages"][0]["atts"][0]["relPath"] == "aa/pic"
    assert threads[0]["id"] == "c1"

