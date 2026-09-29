"""Reader reports on AI-written text ("Something look off?").

The fast-detection half of getting an AI feature right: prompts keep the
failure rate low, and this catches what still slips through within hours,
tied to a durable log instead of an email nobody files.

Each report stores which section it was, the page, the reader's note, and a
snapshot of the text they were actually looking at (AI text changes daily —
without the snapshot a report can't be traced). No IP address or other
identifier is stored; rate limiting happens in memory only.

Stored in the same SQLite file as ai_store (on the Railway volume), so
reports survive deploys.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict, deque

from . import ai_store

logger = logging.getLogger("uvicorn.error")

SECTIONS = {"recap", "significance", "analysis", "player_notes", "statcast_notes", "highlight"}
MAX_NOTE = 1000
MAX_SHOWN_TEXT = 4000
MAX_PAGE = 300
RATE_LIMIT = 5  # reports
RATE_WINDOW_SECONDS = 600

_recent_by_client: dict[str, deque] = defaultdict(deque)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            section TEXT NOT NULL,
            page TEXT,
            note TEXT,
            shown_text TEXT
        )
        """
    )


def rate_limited(client_key: str, now: float | None = None) -> bool:
    """True if this client has already sent RATE_LIMIT reports in the window
    (and records this attempt otherwise). In-memory only, by design."""
    now = now if now is not None else time.monotonic()
    recent = _recent_by_client[client_key]
    while recent and now - recent[0] > RATE_WINDOW_SECONDS:
        recent.popleft()
    if len(recent) >= RATE_LIMIT:
        return True
    recent.append(now)
    return False


def record(section: str, page: str, note: str, shown_text: str) -> int:
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    note = (note or "").strip()[:MAX_NOTE]
    shown_text = (shown_text or "").strip()[:MAX_SHOWN_TEXT]
    page = (page or "")[:MAX_PAGE]
    with ai_store._lock:
        conn = ai_store._connection()
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT INTO feedback (created_at, section, page, note, shown_text) VALUES (?, ?, ?, ?, ?)",
            (time.time(), section, page, note, shown_text),
        )
        conn.commit()
    logger.warning("Reader flagged AI text in %s (%s): %s", section, page, note[:200] or "(no note)")
    return cur.lastrowid


def recent(limit: int = 200) -> list[dict]:
    with ai_store._lock:
        conn = ai_store._connection()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT id, created_at, section, page, note, shown_text FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"id": r[0], "created_at": r[1], "section": r[2], "page": r[3], "note": r[4], "shown_text": r[5]}
        for r in rows
    ]
