from __future__ import annotations

import asyncio
import hashlib
from datetime import date

import httpx

from . import config, game_recap

BASE_URL = "https://statsapi.mlb.com/api/v1"
FRANCHISE_FOUNDED = 1901
MAX_CONCURRENT_REQUESTS = 15


async def _fetch_game_on_date(client: httpx.AsyncClient, team_id: int, iso_date: str) -> dict | None:
    resp = await client.get(
        f"{BASE_URL}/schedule",
        params={
            "teamId": team_id,
            "startDate": iso_date,
            "endDate": iso_date,
            "sportId": 1,
            "gameType": "R",
            "hydrate": "linescore,decisions",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["detailedState"] == "Final":
                return game
    return None


async def _find_candidates(team_id: int, month: int, day: int, exclude_year: int) -> list[dict]:
    years = [y for y in range(FRANCHISE_FOUNDED, exclude_year) if not (y == 1900 and month == 2 and day == 29)]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def fetch(client: httpx.AsyncClient, year: int) -> dict | None:
        try:
            iso_date = date(year, month, day).isoformat()
        except ValueError:
            return None  # Feb 29 in a non-leap year
        async with semaphore:
            try:
                return await _fetch_game_on_date(client, team_id, iso_date)
            except httpx.HTTPError:
                return None

    async with httpx.AsyncClient(timeout=10) as client:
        results = await asyncio.gather(*[fetch(client, year) for year in years])

    return [g for g in results if g is not None]


def _pick_one(candidates: list[dict], seed: str) -> dict:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    index = int(digest, 16) % len(candidates)
    return candidates[index]


async def get_on_this_day(team_id: int = config.TEAM_ID, today: date | None = None) -> dict | None:
    """Pick one real Red Sox game from franchise history that happened on
    today's month/day (excluding this year, since that's just today's game).
    Selection is deterministic per calendar day so it doesn't change on
    refresh, similar to the daily Player Highlight."""
    today = today or date.today()
    candidates = await _find_candidates(team_id, today.month, today.day, exclude_year=today.year)
    if not candidates:
        return None

    game = _pick_one(candidates, seed=f"{today.month:02d}-{today.day:02d}")

    game_pk = game["gamePk"]
    teams = game["teams"]
    is_home = teams["home"]["team"]["id"] == team_id
    us_side, them_side = ("home", "away") if is_home else ("away", "home")
    us = teams[us_side]
    them = teams[them_side]
    decisions = game.get("decisions", {})

    boxscore = await game_recap.get_boxscore(game_pk)

    return {
        "year": int(game["officialDate"][:4]),
        "date": game["officialDate"],
        "opponent": them["team"]["name"],
        "home_or_away": "home" if is_home else "away",
        "won": bool(us.get("isWinner")),
        "our_score": us.get("score"),
        "their_score": them.get("score"),
        "winning_pitcher": (decisions.get("winner") or {}).get("fullName"),
        "losing_pitcher": (decisions.get("loser") or {}).get("fullName"),
        "save_pitcher": (decisions.get("save") or {}).get("fullName"),
        "top_performers": {
            "us": game_recap.top_batting_lines(boxscore, us_side),
            "them": game_recap.top_batting_lines(boxscore, them_side),
        },
        "candidate_count": len(candidates),
    }
