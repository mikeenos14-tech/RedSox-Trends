"""Persistent store for AI-generated text, so a redeploy or restart doesn't
throw away (and re-pay for, and re-word) outputs the site has already shown.

SQLite from the standard library — no new dependency, no separate service.
On Railway the file lives on the attached volume (Railway sets
RAILWAY_VOLUME_MOUNT_PATH automatically once a volume is attached), so it
survives redeploys; without a volume it falls back to a local file, which
behaves exactly like the old in-memory caches (lost on redeploy) but still
works. AI_CACHE_DB overrides the path explicitly.

Rows are appended, never overwritten: the latest row for a key is what's
served, and the full history doubles as an audit log of every AI text the
site has published.

Keys are content-addressed: callers hash whatever determines the output
(input data, or a game_pk) together with the system prompt and model, so
editing a prompt automatically invalidates everything written under the old
one instead of serving stale wording forever.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("uvicorn.error")


def _db_path() -> Path:
    if os.getenv("AI_CACHE_DB"):
        return Path(os.environ["AI_CACHE_DB"])
    if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "ai_cache.sqlite3"
    return Path(__file__).resolve().parents[1] / ".cache" / "ai_cache.sqlite3"


_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                value TEXT NOT NULL,
                model TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS ai_outputs_lookup ON ai_outputs (kind, cache_key, id)")
        _conn.commit()
        persistent = bool(os.getenv("AI_CACHE_DB") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH"))
        logger.info("AI output store: %s (%s)", path, "persistent volume" if persistent else "local, not persistent across deploys")
    return _conn


def make_key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def get(kind: str, cache_key: str):
    """Latest stored value for this key, or None. Never raises — a broken
    store degrades to "regenerate," not to a broken page."""
    try:
        with _lock:
            row = _connection().execute(
                "SELECT value FROM ai_outputs WHERE kind = ? AND cache_key = ? ORDER BY id DESC LIMIT 1",
                (kind, cache_key),
            ).fetchone()
        return json.loads(row[0]) if row else None
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("AI store read failed (%s): %s", kind, exc)
        return None


def put(kind: str, cache_key: str, value, model: str | None = None) -> None:
    try:
        with _lock:
            conn = _connection()
            conn.execute(
                "INSERT INTO ai_outputs (kind, cache_key, value, model, created_at) VALUES (?, ?, ?, ?, ?)",
                (kind, cache_key, json.dumps(value), model, time.time()),
            )
            conn.commit()
    except (sqlite3.Error, OSError, TypeError) as exc:
        logger.warning("AI store write failed (%s): %s", kind, exc)
