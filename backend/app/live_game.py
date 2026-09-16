from __future__ import annotations

import httpx

from . import config, player_highlight

BASE_URL = "https://statsapi.mlb.com/api/v1"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


async def _find_todays_game(team_id: int) -> dict | None:
    today = player_highlight.eastern_today().isoformat()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{BASE_URL}/schedule",
            params={"teamId": team_id, "date": today, "sportId": 1, "gameType": "R"},
        )
        resp.raise_for_status()
        data = resp.json()

    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["abstractGameState"] == "Live":
                return game
    return None


async def get_live_game(team_id: int = config.TEAM_ID) -> dict | None:
    """The Red Sox's currently in-progress game, if any — score, inning,
    count, outs, baserunners, and the current matchup. Returns None on any
    day without a live game right now (the overwhelmingly common case),
    which the frontend uses to hide the ticker entirely rather than show a
    stale or empty widget."""
    game = await _find_todays_game(team_id)
    if game is None:
        return None

    game_pk = game["gamePk"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(LIVE_FEED_URL.format(game_pk=game_pk))
        resp.raise_for_status()
        feed = resp.json()

    linescore = feed["liveData"]["linescore"]
    teams = feed["gameData"]["teams"]
    is_home = teams["home"]["id"] == team_id
    us_side, them_side = ("home", "away") if is_home else ("away", "home")

    them_team = teams[them_side]
    line_teams = linescore.get("teams", {})

    offense = linescore.get("offense", {}) or {}
    defense = linescore.get("defense", {}) or {}
    # "offense" holds whichever team is currently batting — map it back to
    # us/them rather than assuming a fixed side, since that flips inning to
    # inning.
    batting_side_is_us = (offense.get("team") or {}).get("id") == team_id

    # Baserunners live on the current play's matchup, not on the linescore
    # itself — linescore.offense only has the batter/on-deck/in-hole/pitcher.
    current_matchup = feed["liveData"]["plays"].get("currentPlay", {}).get("matchup", {})

    return {
        "game_pk": game_pk,
        "opponent": them_team["name"],
        "opponent_id": them_team["id"],
        "home_or_away": "home" if is_home else "away",
        "inning": linescore.get("currentInning"),
        "inning_half": "top" if linescore.get("isTopInning") else "bottom",
        "outs": linescore.get("outs", 0),
        "balls": linescore.get("balls", 0),
        "strikes": linescore.get("strikes", 0),
        "us_score": (line_teams.get(us_side) or {}).get("runs", 0),
        "them_score": (line_teams.get(them_side) or {}).get("runs", 0),
        "bases": {
            "first": bool(current_matchup.get("postOnFirst")),
            "second": bool(current_matchup.get("postOnSecond")),
            "third": bool(current_matchup.get("postOnThird")),
        },
        "batter": (offense.get("batter") or {}).get("fullName"),
        "pitcher": (defense.get("pitcher") or {}).get("fullName"),
        "batting_team_is_us": batting_side_is_us,
        "last_play": (
            feed["liveData"]["plays"].get("currentPlay", {}).get("result", {}).get("description")
        ),
    }
