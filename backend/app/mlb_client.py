from __future__ import annotations

from datetime import date, timedelta

import httpx

from . import config

BASE_URL = "https://statsapi.mlb.com/api/v1"


async def get_team_standings(team_id: int = config.TEAM_ID, season: int = config.SEASON) -> dict:
    """Fetch the AL standings and return this team's record entry."""
    url = f"{BASE_URL}/standings"
    params = {
        "leagueId": config.LEAGUE_ID,
        "season": season,
        "standingsTypes": "regularSeason",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    for division in data.get("records", []):
        for team_record in division.get("teamRecords", []):
            if team_record["team"]["id"] == team_id:
                return team_record

    raise ValueError(f"Team {team_id} not found in standings for season {season}")


async def get_recent_games(
    team_id: int = config.TEAM_ID,
    days: int = 45,
    season: int = config.SEASON,
) -> list[dict]:
    """Fetch completed regular-season games for this team over the last N days."""
    end = date.today()
    start = end - timedelta(days=days)

    url = f"{BASE_URL}/schedule"
    params = {
        "teamId": team_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "sportId": 1,
        "gameType": "R",
        "hydrate": "linescore",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["detailedState"] != "Final":
                continue

            teams = game["teams"]
            is_home = teams["home"]["team"]["id"] == team_id
            us = teams["home"] if is_home else teams["away"]
            them = teams["away"] if is_home else teams["home"]

            games.append(
                {
                    "date": game["officialDate"],
                    "opponent": them["team"]["name"],
                    "opponent_id": them["team"]["id"],
                    "home_or_away": "home" if is_home else "away",
                    "our_score": us.get("score"),
                    "their_score": them.get("score"),
                    "won": us.get("isWinner", False),
                    "record_after": us.get("leagueRecord"),
                }
            )

    games.sort(key=lambda g: g["date"])
    return games


async def get_league_win_pcts(season: int = config.SEASON) -> dict[int, float]:
    """Fetch current win% for every MLB team (both leagues), keyed by team id."""
    url = f"{BASE_URL}/standings"
    win_pcts: dict[int, float] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for league_id in (103, 104):  # American League, National League
            resp = await client.get(
                url,
                params={
                    "leagueId": league_id,
                    "season": season,
                    "standingsTypes": "regularSeason",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            for division in data.get("records", []):
                for team_record in division.get("teamRecords", []):
                    pct_str = team_record.get("leagueRecord", {}).get("pct")
                    if pct_str is not None:
                        win_pcts[team_record["team"]["id"]] = float(pct_str)

    return win_pcts
