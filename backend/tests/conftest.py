"""Shared fixtures. Every test runs offline: MLB API calls are served from
captured real responses (tests/fixtures, refreshed by capture_fixtures.py)
through httpx's MockTransport, and "today" is pinned explicitly."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app import ai_store, config, player_highlight, season

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


class FakeMLB:
    """Routes requests by URL path suffix (+ optional exact query params) to
    canned JSON. Unmatched requests fail loudly so a test can't silently
    depend on the network."""

    def __init__(self):
        self.routes: list[tuple[str, dict, object]] = []
        self.calls: list[httpx.Request] = []

    def add(self, path_suffix: str, payload, **match):
        self.routes.append((path_suffix, {k: str(v) for k, v in match.items()}, payload))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for suffix, match, payload in self.routes:
            if request.url.path.endswith(suffix) and all(request.url.params.get(k) == v for k, v in match.items()):
                body = payload(request) if callable(payload) else payload
                return httpx.Response(200, json=body)
        raise AssertionError(f"Unexpected request in test: {request.url}")

    def calls_to(self, path_suffix: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path.endswith(path_suffix)]


@pytest.fixture(autouse=True)
def isolate_module_state():
    """season._state is process-global and ensure_fresh() writes to it
    directly; snapshot and restore it so no test leaks its season into the
    next."""
    saved = dict(season._state)
    yield
    season._state.clear()
    season._state.update(saved)


@pytest.fixture
def fake_mlb(monkeypatch):
    api = FakeMLB()
    transport = httpx.MockTransport(api.handler)
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return api


@pytest.fixture
def pin_today(monkeypatch):
    """pin_today(date) — pins "today" (Eastern) everywhere it's read."""

    def pin(day: date):
        monkeypatch.setattr(config, "eastern_today", lambda: day)
        monkeypatch.setattr(player_highlight, "eastern_today", lambda: day)
        return day

    return pin


@pytest.fixture
def set_season(monkeypatch):
    """set_season(year, regular_start, regular_end, season_end) — the season
    the site is "showing," without a network lookup."""

    def apply(year: int, regular_start: date, regular_end: date, season_end: date):
        monkeypatch.setitem(
            season._state,
            "info",
            {"season": year, "regular_start": regular_start, "regular_end": regular_end, "season_end": season_end},
        )
        monkeypatch.setitem(season._state, "checked_on", config.eastern_today())

    return apply


@pytest.fixture
def season_2026(pin_today, set_season):
    pin_today(date(2026, 9, 28))
    set_season(2026, date(2026, 3, 25), date(2026, 9, 27), date(2026, 10, 31))


@pytest.fixture
def temp_ai_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CACHE_DB", str(tmp_path / "ai.sqlite3"))
    monkeypatch.setattr(ai_store, "_conn", None)
    yield tmp_path / "ai.sqlite3"
    if ai_store._conn is not None:
        ai_store._conn.close()
    ai_store._conn = None
