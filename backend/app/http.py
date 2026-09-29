"""One pooled HTTP client for every outbound request (MLB Stats API,
Baseball Savant, Google News) instead of a fresh client — a new connection
pool and TLS handshake — for each call.

`session(timeout=..., headers=...)` is a drop-in for the old
`async with httpx.AsyncClient(timeout=...) as client:` blocks: it yields a
thin wrapper whose `.get()` goes through the shared client with those
defaults, and it never closes the shared client.

The client is kept per event loop (an httpx client is bound to the loop it
was created on). In production that's exactly one; each test's
asyncio.run() gets its own, created through whatever httpx.AsyncClient is
at call time — which is how the test suite's mock transport slots in.
"""
from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager

import httpx

MLB_API = "https://statsapi.mlb.com/api/v1"

_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    existing = _clients.get(loop)
    if existing is None or existing.is_closed:
        existing = httpx.AsyncClient(timeout=15, follow_redirects=True)
        _clients[loop] = existing
    return existing


class _Session:
    def __init__(self, timeout: float, headers: dict | None):
        self._timeout = timeout
        self._headers = headers or {}

    async def get(self, url: str, *, params=None, headers: dict | None = None, timeout: float | None = None) -> httpx.Response:
        return await client().get(
            url,
            params=params,
            headers={**self._headers, **(headers or {})},
            timeout=timeout if timeout is not None else self._timeout,
        )


@asynccontextmanager
async def session(timeout: float = 10, headers: dict | None = None):
    yield _Session(timeout, headers)


async def aclose_all() -> None:
    for c in list(_clients.values()):
        await c.aclose()
    _clients.clear()
