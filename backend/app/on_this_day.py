from __future__ import annotations

import asyncio
import hashlib
from datetime import date

import httpx

from . import config, game_recap, mlb_client

BASE_URL = "https://statsapi.mlb.com/api/v1"
FRANCHISE_FOUNDED = 1901
MAX_CONCURRENT_REQUESTS = 15

# Dates whose game is franchise history, not just a box score — featured
# instead of the daily random pick, with a one-line note. Same rule as
# player_highlight.KNOWN_NICKNAMES: every entry verified against MLB's own
# box score (fetched by date: result, innings, venue, and the named stat line
# all checked, 2026-09-29), plus a standard reference (Baseball-Reference /
# SABR). No AI — the note is shown verbatim.
NOTABLE_GAMES: dict[str, dict] = {
    # box: BOS 7, NYH 6, 11 inn, Fenway Park
    "04-20": {"date": "1912-04-20", "note": "The first official game at Fenway Park: an 11-inning win over the New York Highlanders."},
    # 1986: 20 K for Clemens in the box; the first 20-strikeout nine-inning game in MLB history
    "04-29": {"date": "1986-04-29", "note": "Roger Clemens struck out 20 Mariners, the first 20-strikeout nine-inning game in major-league history."},
    # 2001: 0 opponent hits; Nomo's first start for Boston
    "04-04": {"date": "2001-04-04", "note": "Hideo Nomo no-hit the Orioles in his first start for the Red Sox."},
    # 2002: 0 opponent hits, Fenway Park
    "04-27": {"date": "2002-04-27", "note": "Derek Lowe no-hit the Devil Rays at Fenway Park."},
    # 2008: 0 opponent hits, Fenway Park
    "05-19": {"date": "2008-05-19", "note": "Jon Lester no-hit the Royals at Fenway Park."},
    # 2007: 0 opponent hits; Buchholz's second major-league start
    "09-01": {"date": "2007-09-01", "note": "Clay Buchholz no-hit the Orioles in just his second major-league start."},
    # 1996: 20 K for Clemens in the box, at Tiger Stadium
    "09-18": {"date": "1996-09-18", "note": "Roger Clemens struck out 20 Tigers, the second 20-strikeout game of his career."},
    # 1960: Williams HR in the box; his final game, homering in his last at-bat
    "09-28": {"date": "1960-09-28", "note": "Ted Williams's final game: he homered in his last career at-bat."},
    # 2004 ALCS Game 4: 12 inn, Ortiz HR, BOS 6-4; Boston trailed the series 3-0
    "10-17": {"date": "2004-10-17", "note": "Down three games to none, Boston won in 12 innings on David Ortiz's walk-off homer."},
    # 2004 ALCS Game 7: BOS 10-3 at Yankee Stadium
    "10-20": {"date": "2004-10-20", "note": "The first comeback from a 3-0 series deficit in MLB postseason history."},
    # 1975 WS Game 6: 12 inn, Fisk HR, BOS 7-6
    "10-21": {"date": "1975-10-21", "note": "Carlton Fisk's 12th-inning home run forced a Game 7."},
    # 2004 WS Game 4: BOS 3-0 at St. Louis, sweep
    "10-27": {"date": "2004-10-27", "note": "A sweep of the Cardinals and the first championship since 1918."},
    # 2018 WS Game 5: BOS 5-1 at LA; 2007 WS Game 4: BOS 4-3 at Colorado (also Oct 28)
    "10-28": {
        "date": "2018-10-28",
        "note": "The 2018 title, the fourth in 15 seasons. The 2007 sweep of the Rockies also ended on this date.",
    },
    # 2013 WS Game 6: BOS 6-1 at Fenway Park
    "10-30": {"date": "2013-10-30", "note": "The first title clinched at Fenway Park since 1918."},
}


async def _fetch_game_on_date(client: httpx.AsyncClient, team_id: int, iso_date: str) -> dict | None:
    resp = await client.get(
        f"{BASE_URL}/schedule",
        params={
            "teamId": team_id,
            "startDate": iso_date,
            "endDate": iso_date,
            "sportId": 1,
            # Postseason included: October's best dates (2004, 1975) are all
            # playoff games.
            "gameType": config.ALL_GAME_TYPES,
            "hydrate": "linescore,decisions",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if mlb_client.is_final(game):
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
    today = today or config.eastern_today()
    notable = NOTABLE_GAMES.get(f"{today.month:02d}-{today.day:02d}")
    game = None
    candidate_count = None
    if notable:
        # One request instead of searching ~125 seasons.
        async with httpx.AsyncClient(timeout=10) as client:
            game = await _fetch_game_on_date(client, team_id, notable["date"])
    if game is None:
        notable = None
        candidates = await _find_candidates(team_id, today.month, today.day, exclude_year=today.year)
        if not candidates:
            return None
        game = _pick_one(candidates, seed=f"{today.month:02d}-{today.day:02d}")
        candidate_count = len(candidates)

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
        "opponent_id": them["team"]["id"],
        "home_or_away": "home" if is_home else "away",
        "postseason_label": (
            f"{game.get('seriesDescription')}, Game {game.get('seriesGameNumber')}"
            if game.get("gameType") not in (None, config.REGULAR_SEASON_GAME_TYPE) and game.get("seriesGameNumber")
            else None
        ),
        "note": notable["note"] if notable else None,
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
        "candidate_count": candidate_count,
    }
