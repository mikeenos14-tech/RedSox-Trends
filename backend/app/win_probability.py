from __future__ import annotations

import httpx

from . import config, game_recap

BASE_URL = "https://statsapi.mlb.com/api/v1"


async def _fetch_plays(game_pk: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}/game/{game_pk}/winProbability")
        resp.raise_for_status()
        return resp.json()


async def get_last_game_win_probability(team_id: int = config.TEAM_ID) -> dict | None:
    """Win-probability-by-play for the most recently completed game, plus
    the single biggest swing play. Returns None if there's no completed
    game to look at yet."""
    game = await game_recap.get_last_completed_game(team_id)
    if game is None:
        return None

    game_pk = game["gamePk"]
    is_home = game["teams"]["home"]["team"]["id"] == team_id

    plays = await _fetch_plays(game_pk)

    points = []
    biggest_swing = None
    for play in plays:
        about = play.get("about", {})
        home_wp = play.get("homeTeamWinProbability")
        if home_wp is None:
            continue
        us_wp = home_wp if is_home else (100 - home_wp)
        added = play.get("homeTeamWinProbabilityAdded")
        swing = abs(added) if added is not None else 0

        point = {
            "at_bat_index": about.get("atBatIndex"),
            "inning": about.get("inning"),
            "half": "top" if about.get("isTopInning") else "bottom",
            "us_win_pct": round(us_wp, 1),
            "description": play.get("result", {}).get("description"),
            "is_scoring_play": about.get("isScoringPlay", False),
        }
        points.append(point)

        if biggest_swing is None or swing > biggest_swing["swing"]:
            biggest_swing = {**point, "swing": round(swing, 1)}

    if not points:
        return None

    return {
        "game_pk": game_pk,
        "opponent": game["teams"]["away" if is_home else "home"]["team"]["name"],
        "date": game["officialDate"],
        "points": points,
        "biggest_swing": biggest_swing,
    }
