"""On This Day, Hot/Cold windows, and the next-game data behind Home."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app import config, main, on_this_day, player_stats

# --- On This Day ----------------------------------------------------------------------


def _schedule_with(game_date: str, opponent: str, us: int, them: int, game_type: str = "R", **extra) -> dict:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 1,
                        "officialDate": game_date,
                        "gameType": game_type,
                        "status": {"codedGameState": "F"},
                        "teams": {
                            "home": {"team": {"id": 111, "name": "Boston Red Sox"}, "score": us, "isWinner": us > them},
                            "away": {"team": {"id": 147, "name": opponent}, "score": them},
                        },
                        "decisions": {},
                        **extra,
                    }
                ]
            }
        ]
    }


EMPTY_BOX = {"teams": {"home": {"batters": [], "players": {}}, "away": {"batters": [], "players": {}}}}


def test_notable_date_is_featured_with_its_note(fake_mlb):
    fake_mlb.add("/schedule", _schedule_with("1960-09-28", "Baltimore Orioles", 5, 4), startDate="1960-09-28")
    fake_mlb.add("/boxscore", EMPTY_BOX)
    game = asyncio.run(on_this_day.get_on_this_day(today=date(2026, 9, 28)))
    assert game["year"] == 1960
    assert game["note"] == "Ted Williams's final game: he homered in his last career at-bat."
    assert len(fake_mlb.calls_to("/schedule")) == 1  # no 125-season search


def test_postseason_notable_gets_series_label(fake_mlb):
    fake_mlb.add(
        "/schedule",
        _schedule_with("2004-10-20", "New York Yankees", 10, 3, game_type="L",
                       seriesDescription="AL Championship Series", seriesGameNumber=7),
        startDate="2004-10-20",
    )
    fake_mlb.add("/boxscore", EMPTY_BOX)
    game = asyncio.run(on_this_day.get_on_this_day(today=date(2026, 10, 20)))
    assert game["postseason_label"] == "AL Championship Series, Game 7"
    assert game["note"].startswith("The first comeback from a 3-0 series deficit")


def test_random_pick_searches_postseason_too(fake_mlb):
    fake_mlb.add("/schedule", {"dates": []})
    asyncio.run(on_this_day.get_on_this_day(today=date(2026, 10, 5)))
    calls = fake_mlb.calls_to("/schedule")
    assert len(calls) > 100
    assert all(c.url.params["gameType"] == config.ALL_GAME_TYPES for c in calls)


def test_every_notable_entry_is_well_formed():
    for key, entry in on_this_day.NOTABLE_GAMES.items():
        month, day = map(int, key.split("-"))
        played = date.fromisoformat(entry["date"])
        assert (played.month, played.day) == (month, day), key
        assert entry["note"] and entry["note"][0].isupper() and entry["note"].endswith(".")


# --- Hot/Cold windows -------------------------------------------------------------------


def _pitch_game(i: int, started: bool, ip: str, er: int, so: int, bb: int, hr: int) -> dict:
    return {
        "date": f"2026-{8 + i // 28:02d}-{i % 28 + 1:02d}",
        "stat": {
            "inningsPitched": ip, "gamesStarted": 1 if started else 0, "earnedRuns": er, "runs": er,
            "strikeOuts": so, "baseOnBalls": bb, "homeRuns": hr, "hits": 5, "atBats": 20,
            "battersFaced": 25, "hitByPitch": 0, "sacFlies": 0,
        },
    }


@pytest.fixture
def one_starter(fake_mlb, pin_today):
    pin_today(date(2026, 9, 12))
    # Ten starts: five ugly ones in August, then five sharp ones — only the
    # last five should count as "recent" for a starter.
    log = [_pitch_game(i, True, "5.0", 5, 3, 4, 2) for i in range(5)] + [
        _pitch_game(i, True, "6.0", 1, 8, 1, 0) for i in range(28, 33)
    ]
    season = {
        "gamesPitched": 10, "gamesStarted": 10, "inningsPitched": "55.0", "era": "4.58", "whip": "1.20",
        "earnedRuns": 30, "strikeOuts": 55, "baseOnBalls": 25, "homeRuns": 10, "hits": 50, "atBats": 200,
        "battersFaced": 240, "hitByPitch": 0, "sacFlies": 0, "runs": 30,
    }
    fake_mlb.add("/roster", {"roster": [{"person": {"id": 7}, "position": {"abbreviation": "P"}}]})
    fake_mlb.add("/people", {"people": [{
        "id": 7, "fullName": "Test Starter",
        "stats": [{"type": {"displayName": "season"}, "group": {"displayName": "pitching"}, "splits": [{"stat": season}]}],
    }]})
    fake_mlb.add("/stats", {"stats": [{"splits": log}]}, group="pitching")
    fake_mlb.add("/stats", {"stats": [{"splits": []}]}, group="hitting")


def test_starter_is_judged_on_last_five_starts(one_starter):
    report = asyncio.run(player_stats.get_player_hot_cold_report())
    p = report["pitchers"][0]
    assert p["role"] == "SP" and p["window"] == "last 5 starts"
    assert p["recent"]["ip_display"] == "30.0"  # 5 x 6.0, the August starts excluded
    assert p["form_delta_fip"] > 0  # recent FIP well below season FIP: hot
    assert report["windows"]["starters"] == "last 5 starts"


# --- next game (Home hero) --------------------------------------------------------------


def test_upcoming_schedule_attaches_probable_pitcher_lines(season_2026, monkeypatch):
    game = {
        "game_pk": 1, "date": "2026-09-29", "game_date_utc": "2026-09-30T00:00:00Z", "start_time_tbd": False,
        "opponent": "New York Yankees", "opponent_id": 147, "home_or_away": "away",
        "opponent_record": {"wins": 0, "losses": 0, "pct": ".000"},
        "us_probable_pitcher": "Payton Tolle", "us_probable_pitcher_id": 801139,
        "opponent_probable_pitcher": "Cam Schlittler", "opponent_probable_pitcher_id": 693645,
        "venue": "Yankee Stadium", "game_number": 1,
        "postseason": {"game_type": "F", "series": "AL Wild Card Series", "abbreviation": "ALWC", "game_number": 1,
                       "games_in_series": 3, "if_necessary": False, "status": None, "is_over": False, "winning_team_id": None},
    }

    async def upcoming():
        return [dict(game)]

    async def division():
        return [{"id": 147, "is_target": False}]

    async def season_games():
        return []

    async def records():
        return {111: {"wins": 87, "losses": 75, "pct": ".537"}, 147: {"wins": 93, "losses": 68, "pct": ".578"}}

    async def postseason():
        return []

    def person(pid, era, w, l, so):
        return {"id": pid, "stats": [{"type": {"displayName": "season"}, "group": {"displayName": "pitching"},
                                      "splits": [{"stat": {"era": era, "wins": w, "losses": l, "strikeOuts": so,
                                                           "inningsPitched": "150.0", "whip": "1.00"}}]}]}

    async def people(ids, season=None):
        return [person(801139, "3.03", 9, 6, 171), person(693645, "1.95", 14, 6, 239)]

    monkeypatch.setattr(main.mlb_client, "get_upcoming_games", upcoming)
    monkeypatch.setattr(main.mlb_client, "get_division_standings", division)
    monkeypatch.setattr(main, "_get_season_games_cached", season_games)
    monkeypatch.setattr(main.mlb_client, "get_league_records", records)
    monkeypatch.setattr(main.mlb_client, "get_postseason_games", postseason)
    monkeypatch.setattr(main.player_stats, "_get_people_with_stats", people)

    data = asyncio.run(main._build_upcoming_schedule())
    g = data["games"][0]
    assert g["us_probable_pitcher_line"]["era"] == "3.03"
    assert g["opponent_probable_pitcher_line"]["strikeouts"] == 239
    assert g["opponent_record"]["wins"] == 93  # regular-season record, not the 0-0 postseason one
    assert g["is_division_game"] is False  # October: no division framing
    assert data["team_record"]["wins"] == 87
