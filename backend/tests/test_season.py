"""Season resolution and season-anchored date windows, against MLB's real
2025/2026 calendars."""
from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from app import game_recap, mlb_client, season

from .conftest import load_fixture


@pytest.fixture
def seasons_api(fake_mlb):
    # MLB's "current season" flips to the new year on January 1.
    def current(request):
        return load_fixture("seasons_2026.json")

    fake_mlb.add("/seasons/2025", load_fixture("seasons_2025.json"))
    fake_mlb.add("/seasons/2026", load_fixture("seasons_2026.json"))
    fake_mlb.add("/seasons", current)
    return fake_mlb


def _resolve(monkeypatch, pin_today, day: date) -> int:
    pin_today(day)
    monkeypatch.setitem(season._state, "checked_on", None)
    asyncio.run(season.ensure_fresh())
    return season.current()


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 1, 2), 2025),  # MLB already says 2026, but it hasn't started: keep 2025 up
        (date(2026, 3, 24), 2025),  # day before Opening Day
        (date(2026, 3, 25), 2026),  # Opening Day
        (date(2026, 9, 28), 2026),  # postseason
        (date(2026, 12, 15), 2026),  # offseason keeps the completed season
    ],
)
def test_shown_season_rolls_over_on_opening_day(monkeypatch, pin_today, seasons_api, day, expected):
    assert _resolve(monkeypatch, pin_today, day) == expected


def test_season_lookup_runs_once_per_day(monkeypatch, pin_today, seasons_api):
    _resolve(monkeypatch, pin_today, date(2026, 5, 1))
    before = len(seasons_api.calls)
    asyncio.run(season.ensure_fresh())
    asyncio.run(season.ensure_fresh())
    assert len(seasons_api.calls) == before


def test_failed_lookup_keeps_last_known_season(monkeypatch, pin_today, fake_mlb):
    pin_today(date(2026, 5, 1))
    monkeypatch.setitem(season._state, "info", season._guess(date(2026, 5, 1)))
    monkeypatch.setitem(season._state, "checked_on", None)

    def boom(request):
        raise httpx.ConnectError("down")

    fake_mlb.add("/seasons", boom)
    asyncio.run(season.ensure_fresh())  # must not raise
    assert season.current() == 2026


def test_anchor_date_clamps_to_season_end_in_offseason(pin_today, set_season):
    pin_today(date(2026, 1, 15))
    set_season(2025, date(2025, 3, 18), date(2025, 9, 28), date(2025, 11, 1))
    assert season.anchor_date() == date(2025, 11, 1)
    assert season.regular_season_over()


def test_recent_games_window_never_reaches_previous_season(pin_today, set_season, fake_mlb):
    # April 10: a 200-day lookback would reach last September — the bug that
    # would have folded last year's games into the Season Series Tracker.
    pin_today(date(2026, 4, 10))
    set_season(2026, date(2026, 3, 25), date(2026, 9, 27), date(2026, 10, 31))
    fake_mlb.add("/schedule", {"dates": []})
    asyncio.run(mlb_client.get_recent_games(days=366))
    params = fake_mlb.calls_to("/schedule")[0].url.params
    assert params["startDate"] == "2026-03-25"
    assert params["endDate"] == "2026-04-10"


def test_offseason_still_finds_the_final_game(pin_today, set_season, fake_mlb):
    # Mid-January, the 2025 season is shown; its last game was the Oct 2 Wild
    # Card elimination, weeks before MLB's listed season end (Nov 1).
    pin_today(date(2026, 1, 15))
    set_season(2025, date(2025, 3, 18), date(2025, 9, 28), date(2025, 11, 1))
    fake_mlb.add("/schedule", load_fixture("postseason_2025.json"))
    game = asyncio.run(game_recap.get_last_completed_game())
    assert game["officialDate"] == "2025-10-02"
    params = fake_mlb.calls_to("/schedule")[0].url.params
    assert params["endDate"] == "2025-11-01"
    assert date.fromisoformat(params["startDate"]) <= date(2025, 10, 2)
