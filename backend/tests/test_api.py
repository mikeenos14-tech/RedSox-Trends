"""HTTP-level behavior of the FastAPI app: caching contracts and headers."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(season_2026, monkeypatch):
    # Fresh in-memory caches per test.
    monkeypatch.setitem(main._significance_cache, "game_pk", None)
    monkeypatch.setitem(main._significance_cache, "data", None)
    monkeypatch.setitem(main._live_game_cache, "result", None)
    monkeypatch.setitem(main._live_game_cache, "fetched_at", 0.0)
    return TestClient(main.app)


def test_static_files_must_revalidate(client):
    resp = client.get("/style.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    assert "etag" in resp.headers
    again = client.get("/style.css", headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 304


def test_significance_checks_cache_before_running_checks(client, monkeypatch):
    game = {"gamePk": 824705}
    runs = []

    async def last_game():
        return game

    async def checks(game):
        runs.append(game["gamePk"])
        return {"game_pk": game["gamePk"], "date": "2026-09-27", "findings": [], "complete": True}

    monkeypatch.setattr(main.game_recap, "get_last_completed_game", last_game)
    monkeypatch.setattr(main.significance, "get_game_significance", checks)
    for _ in range(3):
        assert client.get("/api/team/last-game-significance").status_code == 200
    assert runs == [824705]  # dozens of MLB calls once per game, not per page view


def test_incomplete_significance_is_not_cached(client, monkeypatch):
    runs = []

    async def last_game():
        return {"gamePk": 1}

    async def checks(game):
        runs.append(1)
        return {"game_pk": 1, "date": "2026-09-27", "findings": [{"detail": "x"}], "complete": len(runs) > 1}

    async def narrate(findings):
        return "- narrated"

    monkeypatch.setattr(main.game_recap, "get_last_completed_game", last_game)
    monkeypatch.setattr(main.significance, "get_game_significance", checks)
    monkeypatch.setattr(main.ai_recap, "generate_significance_narration", narrate)

    first = client.get("/api/team/last-game-significance").json()
    assert first["narration"] is None  # logs still catching up: show nothing, don't cache
    second = client.get("/api/team/last-game-significance").json()
    assert second["narration"] == "- narrated"
    client.get("/api/team/last-game-significance")
    assert len(runs) == 2


def test_live_game_is_shared_across_visitors(client, monkeypatch):
    fetches = []

    async def live():
        fetches.append(1)
        return None

    monkeypatch.setattr(main.live_game, "get_live_game", live)
    for _ in range(5):
        assert client.get("/api/team/live-game").json() == {"game": None}
    assert len(fetches) == 1


def test_warm_up_survives_one_failing_section(season_2026, monkeypatch):
    ran = []

    def ok(name):
        async def endpoint():
            ran.append(name)

        return endpoint

    async def broken():
        raise RuntimeError("Anthropic down")

    async def fresh():
        return None

    monkeypatch.setattr(main.season, "ensure_fresh", fresh)
    monkeypatch.setattr(main, "team_last_game_recap", broken)
    for name in ("team_last_game_significance", "team_analysis", "players_notes", "players_highlight", "players_statcast_notes"):
        monkeypatch.setattr(main, name, ok(name))
    asyncio.run(main.warm_ai_outputs())
    assert len(ran) == 5
