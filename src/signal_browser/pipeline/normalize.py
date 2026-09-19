from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..utils import first_name, looks_unknown, safe
from .schema import column_names, first_present, select_or_null, table_exists

ProgressFn = Callable[[str, int, int, float], None]


def _load_json(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _hash_layout(digest: str) -> str:
    digest = (digest or "").strip()
    if len(digest) < 4:
        return digest
    return f"{digest[:2]}/{digest[2:4]}/{digest}"


def parse_avatar_info(js: Any) -> dict[str, Optional[str]]:
    """Read Signal Desktop conversation avatar path and keys.

    Current Desktop stores ``avatar`` / ``profileAvatar`` as
    ``{ path, localKey, hash, version }``. Older dumps used string paths.
    """
    path = key1 = key2 = digest = None
    obj = _load_json(js)
    for key in ("avatar", "profileAvatar", "profileAvatarPath", "avatarPath"):
        value = obj.get(key)
        if isinstance(value, dict):
            for nested in ("path", "avatarPath", "filePath"):
                if isinstance(value.get(nested), str) and value[nested] and not path:
                    path = value[nested]
            raw_hash = value.get("hash")
            if isinstance(raw_hash, str) and raw_hash and not digest:
                digest = raw_hash
            for nested in ("localKey", "key", "attachmentKey", "keyMaterial"):
                item = value.get(nested)
                if not isinstance(item, str) or not item:
                    continue
                if not key1:
                    key1 = item
                elif item != key1 and not key2:
                    key2 = item
        elif isinstance(value, str) and value and not path:
            path = value
    fallback = obj.get("localKey")
    if isinstance(fallback, str) and fallback and fallback not in {key1, key2}:
        if not key1:
            key1 = fallback
        elif not key2:
            key2 = fallback
    if not path and digest:
        path = _hash_layout(digest)
    if not path and not digest:
        return {}
    return {"path": path, "key1": key1, "key2": key2, "hash": digest}


def _message_extras(js: Any) -> tuple[Optional[dict], list[dict], Optional[str], str, list[dict]]:
    obj = _load_json(js)
    quote = None
    raw_quote = obj.get("quote")
    if isinstance(raw_quote, dict):
        quote = {
            "sender": raw_quote.get("authorAci") or raw_quote.get("author") or raw_quote.get("id") or "",
            "body": raw_quote.get("text") or raw_quote.get("message") or "",
            "id": raw_quote.get("id"),
        }
    reactions: list[dict] = []
    raw_rx = obj.get("reactions") or []
    if isinstance(raw_rx, list):
        for item in raw_rx:
            if not isinstance(item, dict):
                continue
            emoji = item.get("emoji") or item.get("reaction") or ""
            if emoji:
                reactions.append({
                    "emoji": emoji,
                    "sender": item.get("fromId") or item.get("from") or "",
                })
    edited = obj.get("bodyTimestamp") or obj.get("editMessageTimestamp")
    json_body = obj.get("body") or obj.get("message") or ""
    if not isinstance(json_body, str):
        json_body = ""
    return quote, reactions, str(edited) if edited else None, json_body.strip(), _attachments_from_json(obj)


def _as_att(item: Any, default_type: str) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    nested = item.get("data") if isinstance(item.get("data"), dict) else item
    thumb_obj = nested.get("thumbnail") if isinstance(nested.get("thumbnail"), dict) else {}
    path = nested.get("path") or nested.get("filePath") or item.get("path")
    thumb = nested.get("thumbnailPath") or thumb_obj.get("path")
    if not path and not thumb:
        return None
    return {
        "name": nested.get("fileName") or nested.get("file_name") or "",
        "relPath": path,
        "localKey": nested.get("localKey") or nested.get("key"),
        "key_alt": nested.get("key"),
        "contentType": nested.get("contentType") or nested.get("content_type") or "",
        "attachmentType": nested.get("attachmentType") or default_type,
        "width": nested.get("width"),
        "height": nested.get("height"),
        "caption": nested.get("caption") or "",
        "duration": nested.get("duration"),
        "thumbnailPath": thumb,
        "thumbnailLocalKey": nested.get("thumbnailLocalKey") or thumb_obj.get("localKey"),
        "screenshotPath": nested.get("screenshotPath"),
        "screenshotLocalKey": nested.get("screenshotLocalKey"),
        "flags": nested.get("flags"),
    }


def _attachments_from_json(obj: dict) -> list[dict]:
    out: list[dict] = []
    for item in obj.get("attachments") or []:
        att = _as_att(item, "attachment")
        if att:
            out.append(att)
    sticker = obj.get("sticker")
    if isinstance(sticker, dict):
        att = _as_att(sticker.get("data") or sticker, "sticker")
        if att:
            out.append(att)
    preview = obj.get("preview") or obj.get("previews") or []
    if isinstance(preview, dict):
        preview = [preview]
    for item in preview or []:
        if not isinstance(item, dict):
            continue
        att = _as_att(item.get("image") or item, "preview")
        if att:
            out.append(att)
    return out


def _keep_message(msg: dict) -> bool:
    if (msg.get("body") or "").strip():
        return True
    if msg.get("kind") == "call":
        return True
    if msg.get("quote"):
        return True
    return any(
        a.get("relPath") or a.get("path") or a.get("thumbnailPath")
        for a in (msg.get("atts") or [])
    )


def _call_from_text(mtype: str, body: str, is_out: bool) -> Optional[dict]:
    t = (mtype or "").lower()
    lb = (body or "").strip().lower()
    call_patterns = (
        "incoming call", "outgoing call", "missed call",
        "incoming voice call", "outgoing voice call", "missed voice call",
        "incoming video call", "outgoing video call", "missed video call",
        "voice call", "video call",
    )
    looks_call = ("call" in t) or (t == "call-history") or any(p in lb for p in call_patterns) or lb in {"call", "audio", "video"}
    if not looks_call:
        return None
    is_video = ("video" in t) or ("video" in lb) or (lb == "video")
    missed = ("miss" in t) or ("miss" in lb)
    if missed:
        base = "Missed video call" if is_video else "Missed voice call"
        is_out = False
    elif is_out:
        base = "Outgoing video call" if is_video else "Outgoing voice call"
    else:
        base = "Incoming video call" if is_video else "Incoming voice call"
    return {"body": base, "out": is_out, "video": is_video, "missed": missed}


def _preview_for(msg: dict) -> str:
    if msg.get("kind") == "call":
        return msg.get("body") or "Call"
    body = (msg.get("body") or "").strip()
    if body:
        return body[:140]
    atts = msg.get("atts") or []
    if not atts:
        return ""
    mime = (atts[0].get("contentType") or atts[0].get("mime") or "").lower()
    kind = (atts[0].get("attachmentType") or "").lower()
    if kind == "sticker" or mime.startswith("image/sticker"):
        return "Sticker"
    if mime.startswith("image/"):
        return "Photo"
    if mime.startswith("video/"):
        return "Video"
    if mime.startswith("audio/"):
        return "Voice message"
    return atts[0].get("name") or "Attachment"


def normalize_export(
    db: str | Path,
    *,
    progress: Optional[ProgressFn] = None,
) -> List[Dict[str, Any]]:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if not table_exists(cur, "conversations"):
        con.close()
        raise RuntimeError("decrypted DB missing 'conversations' table")

    conv_cols = column_names(cur, "conversations")
    cur.execute("SELECT COUNT(1) FROM conversations")
    total_convs = cur.fetchone()[0] or 0
    start_av = time.time()
    if progress:
        progress("Conversations", 0, total_convs, start_av)

    select_cols = ", ".join(
        [
            select_or_null(conv_cols, "id"),
            select_or_null(conv_cols, "json"),
            select_or_null(conv_cols, "name"),
            select_or_null(conv_cols, "profileFullName"),
            select_or_null(conv_cols, "profileName"),
            select_or_null(conv_cols, "e164"),
            select_or_null(conv_cols, "serviceId"),
            select_or_null(conv_cols, "type"),
            select_or_null(conv_cols, "isPinned", "isPinned"),
        ]
    )
    cur.execute(f"SELECT {select_cols} FROM conversations")

    conv_name: Dict[str, str] = {}
    is_group: Dict[str, bool] = {}
    by_e164: Dict[str, str] = {}
    by_sid: Dict[str, str] = {}
    conv_avatar: Dict[str, dict] = {}
    conv_pinned: Dict[str, bool] = {}
    conv_raw_name: Dict[str, str] = {}

    processed = 0
    for row in cur.fetchall():
        processed += 1
        if progress and (processed == total_convs or processed % 25 == 0):
            progress("Conversations", processed, total_convs, start_av)
        cid = str(row["id"])
        raw = (row["name"] or row["profileFullName"] or row["profileName"] or
               row["e164"] or row["serviceId"] or f"conv:{cid}")
        group_flag = str(row["type"] or "").lower().startswith("group")
        display = raw
        conv_name[cid] = display
        conv_raw_name[cid] = raw
        is_group[cid] = group_flag
        if row["e164"]:
            by_e164[str(row["e164"])] = first_name(raw) or display
        if row["serviceId"]:
            by_sid[str(row["serviceId"])] = first_name(raw) or display
        js = _load_json(row["json"])
        pinned = bool(row["isPinned"]) if "isPinned" in row.keys() and row["isPinned"] is not None else bool(js.get("isPinned") or js.get("pinned"))
        conv_pinned[cid] = pinned
        avatar_info = parse_avatar_info(row["json"])
        if avatar_info.get("path") or avatar_info.get("hash"):
            conv_avatar[cid] = avatar_info

    if progress:
        progress("Conversations", total_convs, total_convs, start_av)

    def resolve_sender(identifier: Optional[str]) -> str:
        if not identifier:
            return "other"
        if identifier in by_sid:
            return by_sid[identifier]
        if identifier in by_e164:
            return by_e164[identifier]
        return first_name(identifier) or identifier

    if not table_exists(cur, "messages"):
        con.close()
        return []

    msg_cols = column_names(cur, "messages")
    has_attachments = table_exists(cur, "message_attachments")
    ma_cols = column_names(cur, "message_attachments") if has_attachments else set()

    cur.execute("SELECT COUNT(DISTINCT id) FROM messages")
    total_msgs = cur.fetchone()[0] or 0
    start_msg = time.time()
    if progress:
        progress("Messages", 0, total_msgs, start_msg)

    msg_select = [
        "m.id AS mid",
        "m.conversationId AS cid",
        "m.sent_at AS sent_at" if "sent_at" in msg_cols else "NULL AS sent_at",
        "m.received_at AS received_at" if "received_at" in msg_cols else "NULL AS received_at",
        "m.type AS mtype" if "type" in msg_cols else "NULL AS mtype",
        "m.source AS msource" if "source" in msg_cols else "NULL AS msource",
        "m.sourceServiceId AS msource_service" if "sourceServiceId" in msg_cols else "NULL AS msource_service",
        "m.isChangeCreatedByUs AS is_me_change" if "isChangeCreatedByUs" in msg_cols else "NULL AS is_me_change",
        "m.body AS body" if "body" in msg_cols else "NULL AS body",
        "m.json AS mjson" if "json" in msg_cols else "NULL AS mjson",
    ]

    att_select = [
        "NULL AS fileName",
        "NULL AS relPath",
        "NULL AS ord",
        "NULL AS localKey",
        "NULL AS key_alt",
        "NULL AS contentType",
        "NULL AS attachmentType",
        "NULL AS width",
        "NULL AS height",
        "NULL AS caption",
        "NULL AS duration",
        "NULL AS thumbnailPath",
        "NULL AS thumbnailLocalKey",
        "NULL AS screenshotPath",
        "NULL AS screenshotLocalKey",
        "NULL AS flags",
    ]
    join_sql = ""
    order_sql = "ORDER BY m.conversationId, m.sent_at"
    if has_attachments:
        att_select = [
            "ma.fileName AS fileName" if "fileName" in ma_cols else "NULL AS fileName",
            "ma.path AS relPath" if "path" in ma_cols else "NULL AS relPath",
            "ma.orderInMessage AS ord" if "orderInMessage" in ma_cols else "NULL AS ord",
            "ma.localKey AS localKey" if "localKey" in ma_cols else "NULL AS localKey",
            "ma.key AS key_alt" if "key" in ma_cols else "NULL AS key_alt",
            "ma.contentType AS contentType" if "contentType" in ma_cols else "NULL AS contentType",
            "ma.attachmentType AS attachmentType" if "attachmentType" in ma_cols else "NULL AS attachmentType",
            "ma.width AS width" if "width" in ma_cols else "NULL AS width",
            "ma.height AS height" if "height" in ma_cols else "NULL AS height",
            "ma.caption AS caption" if "caption" in ma_cols else "NULL AS caption",
            "ma.duration AS duration" if "duration" in ma_cols else "NULL AS duration",
            "ma.thumbnailPath AS thumbnailPath" if "thumbnailPath" in ma_cols else "NULL AS thumbnailPath",
            "ma.thumbnailLocalKey AS thumbnailLocalKey" if "thumbnailLocalKey" in ma_cols else "NULL AS thumbnailLocalKey",
            "ma.screenshotPath AS screenshotPath" if "screenshotPath" in ma_cols else "NULL AS screenshotPath",
            "ma.screenshotLocalKey AS screenshotLocalKey" if "screenshotLocalKey" in ma_cols else "NULL AS screenshotLocalKey",
            "ma.flags AS flags" if "flags" in ma_cols else "NULL AS flags",
        ]
        join_sql = "LEFT JOIN message_attachments ma ON ma.messageId = m.id"
        order_sql = "ORDER BY m.conversationId, m.sent_at, ma.orderInMessage" if "orderInMessage" in ma_cols else order_sql

    reactions_by_mid: Dict[str, list] = {}
    if table_exists(cur, "reactions"):
        rx_cols = column_names(cur, "reactions")
        mid_col = first_present(rx_cols, ("messageId", "targetTimestamp", "id"))
        emoji_col = first_present(rx_cols, ("emoji", "reaction", "code"))
        from_col = first_present(rx_cols, ("fromId", "sourceServiceId", "authorId"))
        if mid_col and emoji_col:
            sender_expr = from_col if from_col else "NULL"
            cur.execute(f"SELECT {mid_col} AS mid, {emoji_col} AS emoji, {sender_expr} AS sender FROM reactions")
            for rx in cur.fetchall():
                reactions_by_mid.setdefault(str(rx["mid"]), []).append({
                    "emoji": rx["emoji"],
                    "sender": resolve_sender(str(rx["sender"])) if rx["sender"] else "",
                })

    cur.execute(
        f"SELECT {', '.join(msg_select + att_select)} FROM messages m {join_sql} {order_sql}"
    )
    message_rows = cur.fetchall()

    threads: Dict[str, List[Dict[str, Any]]] = {}
    msg_index: Dict[str, Dict[str, Any]] = {}
    thread_meta: Dict[str, Dict[str, Any]] = {}

    seen = 0
    for row in message_rows:
        cid = str(row["cid"])
        label = cid
        display = conv_name.get(cid) or f"conv:{cid}"
        threads.setdefault(label, [])
        if label not in thread_meta:
            thread_meta[label] = {
                "cid": cid,
                "display": display,
                "unknown": looks_unknown(display),
                "group": bool(is_group.get(cid, False)),
                "pinned": bool(conv_pinned.get(cid, False)),
                "avatarInfo": conv_avatar.get(cid),
            }

        mid = str(row["mid"])
        if mid not in msg_index:
            seen += 1
            if progress and (seen == total_msgs or seen % 50 == 0):
                progress("Messages", seen, total_msgs, start_msg)
            t = (row["mtype"] or "").lower()
            is_out = bool("out" in t or row["is_me_change"] == 1)
            sender = "me" if is_out else resolve_sender(row["msource_service"] or row["msource"] or "")
            quote, reactions, edited, json_body, json_atts = _message_extras(row["mjson"])
            body_raw = (row["body"] or "").strip() or json_body
            call = _call_from_text(t, body_raw, is_out)
            if mid in reactions_by_mid:
                reactions = reactions + reactions_by_mid[mid]
            ts = int(row["sent_at"] or 0) or int(row["received_at"] or 0)
            msg = {
                "id": mid,
                "ts": ts,
                "sender": sender,
                "out": call["out"] if call else is_out,
                "body": call["body"] if call else body_raw,
                "atts": list(json_atts),
                "group": bool(is_group.get(cid, False)),
            }
            if call:
                msg["kind"] = "call"
                msg["video"] = call["video"]
                msg["missed"] = call["missed"]
            if quote and (quote.get("body") or quote.get("sender")):
                quote["sender"] = resolve_sender(str(quote.get("sender") or "")) if quote.get("sender") else ""
                msg["quote"] = quote
            if reactions:
                msg["reactions"] = reactions
            if edited:
                msg["edited"] = True
            msg_index[mid] = msg
            threads[label].append(msg)

        if row["relPath"] or row["thumbnailPath"] or row["screenshotPath"]:
            existing = {(a.get("relPath"), a.get("thumbnailPath")) for a in msg_index[mid]["atts"]}
            key = (row["relPath"], row["thumbnailPath"])
            if key in existing:
                continue
            msg_index[mid]["atts"].append({
                "name": row["fileName"] or "",
                "relPath": row["relPath"],
                "localKey": row["localKey"],
                "key_alt": row["key_alt"],
                "contentType": row["contentType"] or "",
                "attachmentType": row["attachmentType"] or "attachment",
                "width": row["width"],
                "height": row["height"],
                "caption": row["caption"] or "",
                "duration": row["duration"],
                "thumbnailPath": row["thumbnailPath"],
                "thumbnailLocalKey": row["thumbnailLocalKey"],
                "screenshotPath": row["screenshotPath"],
                "screenshotLocalKey": row["screenshotLocalKey"],
                "flags": row["flags"],
            })

    if table_exists(cur, "callsHistory"):
        _ingest_calls_history(cur, threads, thread_meta, conv_name, is_group, resolve_sender)

    for label, msgs in list(threads.items()):
        threads[label] = [m for m in msgs if _keep_message(m)]
        threads[label].sort(key=lambda m: (m.get("ts") or 0, str(m.get("id") or "")))

    data: List[Dict[str, Any]] = []
    for label, msgs in threads.items():
        if not msgs:
            continue
        meta = thread_meta.get(label, {})
        last = msgs[-1]
        data.append({
            "id": meta.get("cid") or label,
            "thread": meta.get("display") or label,
            "fsName": safe(meta.get("display") or label),
            "unknown": bool(meta.get("unknown")),
            "group": bool(meta.get("group")),
            "pinned": bool(meta.get("pinned")),
            "avatar": "",
            "avatarEncrypted": False,
            "avatarInfo": meta.get("avatarInfo"),
            "lastTs": last.get("ts") or 0,
            "lastPreview": _preview_for(last),
            "messages": msgs,
        })

    data.sort(key=lambda t: (not t.get("pinned"), -(t.get("lastTs") or 0), (t.get("thread") or "").lower()))
    con.close()
    return data


def _ingest_calls_history(cur, threads, thread_meta, conv_name, is_group, resolve_sender) -> None:
    cols = column_names(cur, "callsHistory")
    col_cid = first_present(cols, ("conversationId", "cid", "threadId"))
    col_ts = first_present(cols, ("timestamp", "startedAt", "startTimestamp", "sent_at", "time"))
    col_ty = first_present(cols, ("type", "callType", "direction", "status"))
    col_du = first_present(cols, ("duration", "callDurationSeconds", "endedTimestamp"))
    col_peer = first_present(cols, ("peerId", "ringerId", "startedById"))
    if col_cid and col_ts and col_ty:
        cur.execute(
            f"SELECT {col_cid} AS cid, {col_ts} AS ts, {col_ty} AS ctype, {col_du or 'NULL'} AS dur FROM callsHistory"
        )
        for row in cur.fetchall():
            cid = str(row["cid"])
            _append_call(threads, thread_meta, cid, row, conv_name, is_group, cid)
    elif col_peer and col_ts and col_ty:
        cur.execute(
            f"SELECT {col_peer} AS pid, {col_ts} AS ts, {col_ty} AS ctype, {col_du or 'NULL'} AS dur FROM callsHistory"
        )
        for row in cur.fetchall():
            name = resolve_sender(row["pid"])
            label = safe(name or "Call")
            _append_call(threads, thread_meta, label, row, {label: name}, {}, label)


def _append_call(threads, thread_meta, label, row, conv_name, is_group, cid) -> None:
    t = (row["ctype"] or "").lower()
    is_video = "video" in t
    missed = "miss" in t
    outb = "out" in t or "placed" in t
    if missed:
        base = "Missed video call" if is_video else "Missed voice call"
        outb = False
    elif outb:
        base = "Outgoing video call" if is_video else "Outgoing voice call"
    elif "in" in t or "received" in t:
        base = "Incoming video call" if is_video else "Incoming voice call"
    else:
        base = "Call"
    ts = int(row["ts"] or 0)
    ts = ts if ts > 10_000 else ts * 1000
    threads.setdefault(label, []).append({
        "id": f"call-{ts}",
        "ts": ts,
        "sender": "me" if outb else "",
        "out": outb,
        "body": base,
        "kind": "call",
        "missed": missed,
        "video": is_video,
        "atts": [],
        "group": bool(is_group.get(cid, False)) if not isinstance(is_group, dict) else bool(is_group.get(cid, False)),
    })
    thread_meta.setdefault(label, {
        "cid": cid,
        "display": conv_name.get(cid) or label if isinstance(conv_name, dict) else label,
        "unknown": looks_unknown(str(conv_name.get(cid) or label) if isinstance(conv_name, dict) else label),
        "group": bool(is_group.get(cid, False)) if isinstance(is_group, dict) else False,
        "pinned": False,
        "avatarInfo": None,
    })
