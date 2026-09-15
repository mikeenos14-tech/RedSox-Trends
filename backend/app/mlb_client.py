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
                    "game_pk": game["gamePk"],
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


async def get_division_standings(team_id: int = config.TEAM_ID, season: int = config.SEASON) -> list[dict]:
    """Fetch the standings for this team's own division, sorted by rank."""
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
        team_ids = [tr["team"]["id"] for tr in division.get("teamRecords", [])]
        if team_id not in team_ids:
            continue

        teams = []
        for tr in division.get("teamRecords", []):
            record = tr.get("leagueRecord", {})
            teams.append(
                {
                    "id": tr["team"]["id"],
                    "name": tr["team"]["name"],
                    "wins": record.get("wins"),
                    "losses": record.get("losses"),
                    "pct": record.get("pct"),
                    "games_back": tr.get("gamesBack"),
                    "streak": (tr.get("streak") or {}).get("streakCode"),
                    "division_rank": tr.get("divisionRank"),
                    "is_target": tr["team"]["id"] == team_id,
                }
            )
        teams.sort(key=lambda t: int(t["division_rank"]))
        return teams

    raise ValueError(f"Division for team {team_id} not found in standings for season {season}")


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


async def get_upcoming_games(team_id: int = config.TEAM_ID, count: int = 10, season: int = config.SEASON) -> list[dict]:
    """Fetch the next `count` not-yet-played games, with probable pitchers."""
    start = date.today()
    end = start + timedelta(days=30)  # generous window in case of postponements/gaps

    url = f"{BASE_URL}/schedule"
    params = {
        "teamId": team_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "sportId": 1,
        "gameType": "R",
        "hydrate": "probablePitcher",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["abstractGameState"] not in ("Preview",):
                continue

            teams = game["teams"]
            is_home = teams["home"]["team"]["id"] == team_id
            us = teams["home"] if is_home else teams["away"]
            them = teams["away"] if is_home else teams["home"]
            them_record = them.get("leagueRecord", {})

            games.append(
                {
                    "date": game["officialDate"],
                    "game_date_utc": game["gameDate"],
                    "opponent": them["team"]["name"],
                    "opponent_id": them["team"]["id"],
                    "home_or_away": "home" if is_home else "away",
                    "opponent_record": {
                        "wins": them_record.get("wins"),
                        "losses": them_record.get("losses"),
                        "pct": them_record.get("pct"),
                    },
                    "us_probable_pitcher": (us.get("probablePitcher") or {}).get("fullName"),
                    "opponent_probable_pitcher": (them.get("probablePitcher") or {}).get("fullName"),
                    "venue": (game.get("venue") or {}).get("name"),
                    "game_number": game.get("gameNumber", 1),
                }
            )

    games.sort(key=lambda g: g["game_date_utc"])
    return games[:count]


async def get_wildcard_standings(team_id: int = config.TEAM_ID, season: int = config.SEASON) -> list[dict]:
    """Fetch the Wild Card standings (division leaders excluded — they're
    already in via the division race, so this is specifically who's
    competing for the remaining playoff spots)."""
    url = f"{BASE_URL}/standings"
    params = {
        "leagueId": config.LEAGUE_ID,
        "season": season,
        "standingsTypes": "wildCard",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    teams = []
    for division in data.get("records", []):
        for tr in division.get("teamRecords", []):
            record = tr.get("leagueRecord", {})
            teams.append(
                {
                    "id": tr["team"]["id"],
                    "name": tr["team"]["name"],
                    "wins": record.get("wins"),
                    "losses": record.get("losses"),
                    "pct": record.get("pct"),
                    "wildcard_rank": tr.get("wildCardRank"),
                    "wildcard_games_back": tr.get("wildCardGamesBack"),
                    "elimination_number": tr.get("wildCardEliminationNumber"),
                    "clinched": bool(tr.get("clinched")),
                    "streak": (tr.get("streak") or {}).get("streakCode"),
                    "is_target": tr["team"]["id"] == team_id,
                }
            )

    teams.sort(key=lambda t: int(t["wildcard_rank"]))
    return teams


def build_season_series(games: list[dict], team_id: int = config.TEAM_ID) -> dict[int, dict]:
    """Aggregate a game log (as returned by get_recent_games) into a
    per-opponent won-loss record for the season."""
    series: dict[int, dict] = {}
    for g in games:
        opp_id = g["opponent_id"]
        entry = series.setdefault(opp_id, {"opponent": g["opponent"], "opponent_id": opp_id, "wins": 0, "losses": 0})
        if g["won"]:
            entry["wins"] += 1
        else:
            entry["losses"] += 1
    return series
