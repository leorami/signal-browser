from pathlib import Path
from importlib import resources as importlib_resources
import json
import sqlite3
from signal_browser.exporter import run_export


def test_packaged_assets_present():
    tpl = importlib_resources.files("signal_browser").joinpath("assets", "template.html")
    css = importlib_resources.files("signal_browser").joinpath("assets", "styles.css")
    js = importlib_resources.files("signal_browser").joinpath("assets", "viewer.js")
    assert tpl.is_file()
    assert css.is_file()
    assert js.is_file()
    assert tpl.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert "--signal:" in css.read_text(encoding="utf-8")
    assert ".sidebar-scroll{" in css.read_text(encoding="utf-8")
    assert ".empty-hero p{" in css.read_text(encoding="utf-8")


def test_template_contains_call_rendering():
    js = importlib_resources.files("signal_browser").joinpath("assets", "viewer.js").read_text(encoding="utf-8")
    assert "if (m.kind === 'call')" in js
    assert "row.className = 'call'" in js
    assert "m.video ? '📹' : '📞'" in js
    assert "pill.append" in js


def test_css_contains_call_styles():
    css = importlib_resources.files("signal_browser").joinpath("assets", "styles.css").read_text(encoding="utf-8")
    assert ".call{" in css
    assert ".call .pill{" in css
    assert ".call.missed .pill{" in css


def test_template_linkify_function():
    js = importlib_resources.files("signal_browser").joinpath("assets", "viewer.js").read_text(encoding="utf-8")
    assert "function linkify(text)" in js
    assert "urlRe" in js
    assert "target = '_blank'" in js or 'target="_blank"' in js


def test_viewer_cross_chat_search():
    js = importlib_resources.files("signal_browser").joinpath("assets", "viewer.js").read_text(encoding="utf-8")
    assert "function localMessageHits" in js
    assert "function messageMatches" in js
    assert "search-hits" in js
    html = importlib_resources.files("signal_browser").joinpath("assets", "template.html").read_text(encoding="utf-8")
    assert 'id="search-hits"' in html
    app = importlib_resources.files("signal_browser").joinpath("assets", "app.html").read_text(encoding="utf-8")
    assert "Backup" in app
    assert "History" in app
    assert "do not restore Signal Desktop, iPhone, or other linked devices" in app
    assert "does not restore Signal Desktop, iPhone, or other linked devices" in app
    assert "does not restore Signal" in app
    html_static = importlib_resources.files("signal_browser").joinpath("assets", "template.html").read_text(encoding="utf-8")
    assert "does not restore Signal" in html_static
    assert 'id="history-banner"' in app
    assert "<h2>Unlock</h2>" in app
    assert "Unlock Signal Browser" not in app
    assert 'id="delete-panel"' in app
    assert "/api/snapshot/delete" in app
    logo = importlib_resources.files("signal_browser").joinpath("assets", "logo.svg").read_text(encoding="utf-8")
    source = importlib_resources.files("signal_browser").joinpath("assets", "logo-signal.svg").read_text(encoding="utf-8")
    wordmark_source = importlib_resources.files("signal_browser").joinpath("assets", "wordmark-signal.svg")
    assert wordmark_source.is_file()
    assert 'fill="#3B45FD"' in logo
    assert "M64 0c3.32" in logo
    assert "M64 0c3.32" in source
    assert 'cx="101"' in logo
    assert 'cx="101"' not in source
    appicon = Path(__file__).resolve().parents[1] / "packaging" / "logo-appicon.svg"
    icon_svg = appicon.read_text(encoding="utf-8")
    assert 'fill="#3B45FD"' in icon_svg
    assert 'viewBox="0 0 128 128"' in icon_svg
    assert 'fill="#fff"' in icon_svg
    assert 'cx="101"' in icon_svg
    assert "<rect width=" not in logo
    css = importlib_resources.files("signal_browser").joinpath("assets", "styles.css").read_text(encoding="utf-8")
    assert "card input.invalid" in css
    assert ".card .error:not(:empty)" in css
    assert "friendlyUnlockError" in app
    assert "function appendHighlighted" in js
    assert "mark.className = 'hit'" in js
    assert "--hit-mark:" in css
    assert "--hit-ring:" in css
    assert '<!--__LOGO__-->' in app
    assert '<!--__WORDMARK__-->' not in app


def test_avatar_initials_fallback():
    js = importlib_resources.files("signal_browser").joinpath("assets", "viewer.js").read_text(encoding="utf-8")
    assert "function liAvatar(t" in js
    assert "initials(name)" in js or "initials(t.thread)" in js
    assert "dotAvatar" in js


def test_html_output_structure(tmp_dirs, tmp_path):
    src, out = tmp_dirs
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT, duration INTEGER)")
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test User", "private"))
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)",
                   (1, "1", 1678886400000, "incoming", "Hello world", 0))
    conn.commit()
    conn.close()

    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_content
    assert "<title>Signal Browser</title>" in html_content
    assert "<!--__LOGO__-->" not in html_content
    assert "M64 0c3.32" in html_content
    assert 'class="app"' in html_content
    assert 'class="sidebar"' in html_content
    assert 'class="main"' in html_content
    assert '<script id="data" type="application/json">' in html_content
    assert '<script id="meta" type="application/json">' in html_content
    assert "/*__INLINE_CSS__*/" not in html_content
    assert "/*__VIEWER_JS__*/" not in html_content
    assert ".sidebar{" in html_content
    assert "function initViewer" in html_content
    data = json.loads(html_content.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert data[0]["thread"] == "Test User"
    assert data[0]["messages"][0]["body"] == "Hello world"


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_html_export_search_avatar_and_stays_static(tmp_dirs, tmp_path):
    src, out = tmp_dirs
    rel = "aa/bb/face"
    dest = src / "aa" / "bb"
    dest.mkdir(parents=True)
    (dest / "face").write_bytes(TINY_PNG)
    db_path = tmp_path / "html.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute(
        "INSERT INTO conversations (id, name, type, json) VALUES (?, ?, ?, ?)",
        ("1", "Ada", "private", json.dumps({"avatar": {"path": rel}})),
    )
    cursor.execute(
        "INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "1", 1678886400000, "incoming", "secret recipe", 0),
    )
    conn.commit()
    conn.close()

    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    assert 'id="gate-unlock"' not in html_content
    assert 'id="btn-history"' not in html_content
    assert "function localMessageHits" in html_content
    assert "function initViewer" in html_content
    assert "secret recipe" in html_content
    data = json.loads(html_content.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert data[0]["avatar"].startswith("assets/avatars/")
    assert not data[0]["avatarEncrypted"]
    avatar_file = out / data[0]["avatar"]
    assert avatar_file.is_file()
    assert avatar_file.read_bytes().startswith(b"\x89PNG")
    assert (out / "index.html").is_file()
