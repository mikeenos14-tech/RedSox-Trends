"""One in-memory caching primitive for every endpoint.

main.py used to hand-roll ~20 caches in five slightly different shapes
(time-based, per-day, per-game, per-input-hash, per-id-per-day), each with
a module-level asyncio.Lock. That meant one global lock per cache (a slow
team page blocked every other team's page) and locks created at import time
(bound to whatever event loop existed then, on Python 3.9). Memo covers all
five shapes with one behavior:

- `await memo.get(key, compute)` returns the stored value for `key`, or runs
  `compute()` once — concurrent callers for the same key wait for that one
  run instead of each fetching (single flight). Different keys never block
  each other.
- The key *is* the invalidation rule: a date string for "once per day", a
  gamePk for "once per game", an input hash for "only when inputs change",
  `(id, date)` for per-page caches. Old keys age out (bounded size).
- `ttl` adds time-based expiry for "at most every N seconds".
- `store_if` lets a caller decline to cache a result (e.g. partial data).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable

_MISS = object()
_registry: list["Memo"] = []


def stable_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class Memo:
    def __init__(self, ttl: float | None = None, max_keys: int = 8):
        self.ttl = ttl
        self.max_keys = max_keys
        self._values: dict[Any, tuple[Any, float]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}
        _registry.append(self)

    def _fresh(self, key: Any) -> Any:
        entry = self._values.get(key)
        if entry is None:
            return _MISS
        value, stored_at = entry
        if self.ttl is not None and time.monotonic() - stored_at >= self.ttl:
            return _MISS
        return value

    def _store(self, key: Any, value: Any) -> None:
        self._values.pop(key, None)
        self._values[key] = (value, time.monotonic())
        while len(self._values) > self.max_keys:
            oldest = next(iter(self._values))
            del self._values[oldest]
            self._locks.pop(oldest, None)

    async def get(
        self,
        key: Any,
        compute: Callable[[], Awaitable[Any]],
        store_if: Callable[[Any], bool] | None = None,
    ) -> Any:
        hit = self._fresh(key)
        if hit is not _MISS:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._fresh(key)  # another caller may have filled it while we waited
            if hit is not _MISS:
                return hit
            value = await compute()
            if store_if is None or store_if(value):
                self._store(key, value)
            return value

    def clear(self) -> None:
        self._values.clear()
        self._locks.clear()


def clear_all() -> None:
    """Every Memo in the process (tests; never needed in production)."""
    for memo in _registry:
        memo.clear()
