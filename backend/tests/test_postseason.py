"""Postseason and schedule handling, against real captured MLB responses."""
from __future__ import annotations

import asyncio
import copy

import pytest

from app import config, mlb_client, trends

from .conftest import load_fixture

BOS, NYY = 111, 147


def _postseason_games(fake_mlb, season_2026):
    fake_mlb.add("/schedule", load_fixture("postseason_2025.json"), gameType="F,D,L,W")
    return asyncio.run(mlb_client.get_postseason_games(season=2025))


def _as_of(games: list[dict], played: int) -> list[dict]:
    """The real 2025 series rewound to just after `played` games."""
    games = copy.deepcopy(games)
    for g in games[played:]:
        g.update(state="preview", won=None, our_score=None, their_score=None)
        g["postseason"].update(status=None, is_over=False, winning_team_id=None)
    return games


# --- completed-game detection -------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        ({"codedGameState": "F", "detailedState": "Final"}, True),
        # Rain-shortened but official: the old detailedState == "Final" check dropped these.
        ({"codedGameState": "F", "detailedState": "Completed Early"}, True),
        ({"codedGameState": "D", "detailedState": "Postponed", "abstractGameState": "Final"}, False),
        ({"codedGameState": "C", "detailedState": "Cancelled", "abstractGameState": "Final"}, False),
        ({"codedGameState": "I", "detailedState": "In Progress"}, False),
    ],
)
def test_is_final(status, expected):
    assert mlb_client.is_final({"status": status}) is expected


def test_postseason_info_is_none_for_regular_season():
    assert mlb_client.postseason_info({"gameType": "R"}) is None


# --- series state across a real series -----------------------------------------


def test_real_2025_series_parses(fake_mlb, season_2026):
    games = _postseason_games(fake_mlb, season_2026)
    assert [g["postseason"]["game_number"] for g in games] == [1, 2, 3]
    assert [g["won"] for g in games] == [True, False, False]
    assert [g["postseason"]["status"] for g in games] == ["BOS leads 1-0", "Series tied 1-1", "NYY wins 2-1"]
    assert all(g["opponent_id"] == NYY and g["home_or_away"] == "away" for g in games)


@pytest.mark.parametrize(
    "played, phase, status, next_game_number, record",
    [
        (0, "in_series", None, 1, (0, 0)),
        (1, "in_series", "BOS leads 1-0", 2, (1, 0)),
        (2, "in_series", "Series tied 1-1", 3, (1, 1)),
        (3, "eliminated", "NYY wins 2-1", None, (1, 2)),
    ],
)
def test_series_state_at_every_stage(fake_mlb, season_2026, played, phase, status, next_game_number, record):
    summary = trends.summarize_postseason(_as_of(_postseason_games(fake_mlb, season_2026), played), BOS)
    assert summary["phase"] == phase
    assert summary["status"] == status
    assert (summary["next_game"] or {}).get("game_number") == next_game_number
    assert (summary["record"]["wins"], summary["record"]["losses"]) == record
    assert summary["series"] == "AL Wild Card Series"


def test_series_won_waits_for_next_round_then_champions(fake_mlb, season_2026):
    games = _postseason_games(fake_mlb, season_2026)
    games[-1]["postseason"]["winning_team_id"] = BOS
    assert trends.summarize_postseason(games, BOS)["phase"] == "awaiting_next_round"
    for g in games:
        g["postseason"]["game_type"] = "W"
    assert trends.summarize_postseason(games, BOS)["phase"] == "won_world_series"


def test_no_postseason_games_means_no_block():
    assert trends.summarize_postseason([], BOS) is None


# --- upcoming schedule ------------------------------------------------------------


def test_upcoming_includes_postseason_with_series_context(fake_mlb, season_2026):
    fake_mlb.add("/schedule", load_fixture("upcoming_2026_wc.json"))
    games = asyncio.run(mlb_client.get_upcoming_games())

    assert [g["date"] for g in games] == ["2026-09-29", "2026-09-30", "2026-10-01"]
    assert [g["postseason"]["game_number"] for g in games] == [1, 2, 3]
    assert [g["postseason"]["if_necessary"] for g in games] == [False, False, True]
    assert games[0]["us_probable_pitcher"] == "Payton Tolle"
    assert games[0]["opponent_probable_pitcher"] == "Cam Schlittler"

    # Every game type is requested — the regular-season-only filter is what
    # made the whole site go dark once the team clinched.
    assert fake_mlb.calls_to("/schedule")[0].url.params["gameType"] == config.ALL_GAME_TYPES


def test_upcoming_hides_if_necessary_game_the_series_never_needed(fake_mlb, season_2026):
    data = load_fixture("upcoming_2026_wc.json")
    game3 = data["dates"][-1]["games"][0]
    game3["seriesStatus"].update(isOver=True, result="BOS wins 2-0")
    fake_mlb.add("/schedule", data)
    games = asyncio.run(mlb_client.get_upcoming_games())
    assert [g["postseason"]["game_number"] for g in games] == [1, 2]


def test_upcoming_uses_eastern_date_not_utc(fake_mlb, pin_today, set_season):
    from datetime import date

    pin_today(date(2026, 9, 29))
    fake_mlb.add("/schedule", load_fixture("upcoming_2026_wc.json"))
    asyncio.run(mlb_client.get_upcoming_games())
    assert fake_mlb.calls_to("/schedule")[0].url.params["startDate"] == "2026-09-29"


# --- recent games ------------------------------------------------------------------


def test_suspended_and_resumed_game_counts_once(fake_mlb, pin_today, set_season):
    from datetime import date

    pin_today(date(2025, 7, 3))
    set_season(2025, date(2025, 3, 18), date(2025, 9, 28), date(2025, 11, 1))
    fake_mlb.add("/schedule", load_fixture("schedule_2025_suspended.json"))
    games = asyncio.run(mlb_client.get_recent_games(days=10))
    pks = [g["game_pk"] for g in games]
    assert pks.count(777294) == 1
    assert len(pks) == len(set(pks)) == 5


def test_postseason_game_has_no_season_record(fake_mlb, season_2026):
    fake_mlb.add("/schedule", load_fixture("postseason_2025.json"))
    games = asyncio.run(mlb_client.get_recent_games(days=10, game_types=config.ALL_GAME_TYPES))
    assert games and all(g["record_after"] is None for g in games)
    assert all(g["postseason"]["abbreviation"] == "ALWC" for g in games)
