"""Offseason Home: when the season counts as over, how it ended, and whose
seasons make the "best" list."""
from __future__ import annotations

import asyncio
import copy

import pytest

from app import mlb_client, season_review, trends

from .conftest import load_fixture

BOS = 111


@pytest.mark.parametrize(
    "phase, upcoming, regular_over, expected",
    [
        ("eliminated", False, True, True),
        ("won_world_series", False, True, True),
        ("in_series", False, True, False),  # between games of a series
        ("awaiting_next_round", False, True, False),
        (None, False, True, True),  # missed the postseason
        (None, False, False, False),  # the regular season is still going
        ("eliminated", True, True, False),  # next season's games already scheduled
    ],
)
def test_season_is_over(phase, upcoming, regular_over, expected):
    postseason = {"phase": phase} if phase else None
    assert season_review.season_is_over(postseason, upcoming, regular_over) is expected


def _games_2025(fake_mlb, season_2026):
    fake_mlb.add("/schedule", load_fixture("postseason_2025.json"))
    return asyncio.run(mlb_client.get_postseason_games(season=2025))


def test_real_2025_ending(fake_mlb, season_2026):
    games = _games_2025(fake_mlb, season_2026)
    path = season_review.postseason_path(games)
    assert path == [{
        "series": "AL Wild Card Series", "abbreviation": "ALWC", "game_type": "F",
        "opponent": "New York Yankees", "wins": 1, "losses": 2, "won": False,
    }]
    assert season_review.outcome_text(path) == "Eliminated in the AL Wild Card Series by the New York Yankees, 1-2."
    assert trends.summarize_postseason(games, BOS)["phase"] == "eliminated"


def test_champion_and_missed_postseason_wording():
    ws = [{"series": "World Series", "abbreviation": "WS", "game_type": "W", "opponent": "Los Angeles Dodgers", "wins": 4, "losses": 2, "won": True}]
    assert season_review.outcome_text(ws) == "World Series champions."
    assert season_review.outcome_text([]) == "Missed the postseason."


def test_best_seasons_require_real_workloads():
    roster = {
        "hitters": [
            {"id": 1, "name": "Regular", "position": "1B", "season": {"pa": 600, "ops_plus": 125, "ops": 0.85, "hr": 25}},
            {"id": 2, "name": "Callup", "position": "LF", "season": {"pa": 40, "ops_plus": 210, "ops": 1.2, "hr": 5}},
        ],
        "pitchers": [
            {"id": 3, "name": "Ace", "role": "SP", "season": {"ip": 190.0, "era_minus": 70, "era": 2.9, "ip_display": "190.0", "fip": 3.1}},
            {"id": 4, "name": "Spot starter", "role": "SP", "season": {"ip": 30.0, "era_minus": 40, "era": 1.6, "ip_display": "30.0", "fip": 3.0}},
            {"id": 5, "name": "Closer", "role": "RP", "season": {"ip": 60.0, "era_minus": 45, "era": 1.9, "ip_display": "60.0", "fip": 2.4}},
        ],
    }
    best = season_review.best_seasons(roster)
    assert [h["name"] for h in best["hitters"]] == ["Regular"]
    assert [p["name"] for p in best["pitchers"]] == ["Ace", "Closer"]


def test_openers_from_next_seasons_schedule(fake_mlb, season_2026):
    def game(date, home_id, away_id, venue):
        return {"officialDate": date, "gameDate": f"{date}T20:10:00Z", "venue": {"name": venue},
                "teams": {"home": {"team": {"id": home_id, "name": "Home"}}, "away": {"team": {"id": away_id, "name": "Away"}}}}

    fake_mlb.add("/schedule", {"dates": [{"games": [game("2027-03-25", 136, BOS, "T-Mobile Park")]},
                                         {"games": [game("2027-04-02", BOS, 147, "Fenway Park")]}]}, season=2027)
    openers = asyncio.run(season_review.next_season_openers())
    assert openers["season"] == 2027
    assert openers["opening_day"]["home_or_away"] == "away" and openers["opening_day"]["venue"] == "T-Mobile Park"
    assert openers["home_opener"]["date"] == "2027-04-02"
