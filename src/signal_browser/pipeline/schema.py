from __future__ import annotations

import sqlite3
from typing import Iterable, Optional, Set


def table_names(cur: sqlite3.Cursor) -> Set[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return name in table_names(cur)


def column_names(cur: sqlite3.Cursor, table: str) -> Set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] if not isinstance(row, sqlite3.Row) else row["name"] for row in cur.fetchall()}


def first_present(columns: Set[str], candidates: Iterable[str]) -> Optional[str]:
    for name in candidates:
        if name in columns:
            return name
    return None


def select_or_null(columns: Set[str], name: str, alias: Optional[str] = None) -> str:
    label = alias or name
    if name in columns:
        return f"{name} AS {label}"
    return f"NULL AS {label}"
