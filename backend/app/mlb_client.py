from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

from . import config
from . import http
from . import season as season_mod

BASE_URL = http.MLB_API


def is_final(game: dict) -> bool:
    """True for any official completed game. `codedGameState == "F"` rather
    than `detailedState == "Final"`: a rain-shortened official game reports
    detailedState "Completed Early" (4-5 per season league-wide) and was
    silently dropped by the string check, while postponed ("D") and
    cancelled ("C") games — which also have abstractGameState "Final" — are
    correctly excluded."""
    return (game.get("status") or {}).get("codedGameState") == "F"


def postseason_info(game: dict) -> dict | None:
    """Series context for a postseason game (None for a regular-season one).
    `status` is MLB's own series summary as of this game — e.g. "BOS leads
    1-0" after a finished Game 1 — and is None before a series has started."""
    if game.get("gameType") in (None, config.REGULAR_SEASON_GAME_TYPE):
        return None
    series_status = game.get("seriesStatus") or {}
    return {
        "game_type": game.get("gameType"),
        "series": game.get("seriesDescription"),
        "abbreviation": series_status.get("abbreviation"),
        "game_number": game.get("seriesGameNumber"),
        "games_in_series": game.get("gamesInSeries"),
        "if_necessary": game.get("ifNecessary") == "Y",
        "status": series_status.get("result"),
        "is_over": bool(series_status.get("isOver")),
        "winning_team_id": (series_status.get("winningTeam") or {}).get("id"),
    }


async def get_team_standings(team_id: int = config.TEAM_ID, season: int | None = None) -> dict:
    """Fetch this team's standings record entry. Red Sox callers only ever
    need the AL (id 103), but a clicked-into opponent — e.g. an interleague
    matchup — can be an NL team (104), so this tries both leagues rather
    than assuming AL like the original Red Sox-only version did."""
    season = season or season_mod.current()
    url = f"{BASE_URL}/standings"
    for league_id in (config.LEAGUE_ID, 104 if config.LEAGUE_ID == 103 else 103):
        params = {
            "leagueId": league_id,
            "season": season,
            "standingsTypes": "regularSeason",
        }
        async with http.session(timeout=10) as client:
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
    season: int | None = None,
    game_types: str = config.REGULAR_SEASON_GAME_TYPE,
) -> list[dict]:
    """Fetch completed games for this team over the last N days. Regular
    season only by default — callers computing season stats must not have
    October games blended in; callers that care about recent workload (the
    bullpen report) pass config.ALL_GAME_TYPES."""
    season = season or season_mod.current()
    # Anchored to the shown season (not the raw clock) so the season's final
    # games stay visible all winter, and clamped to its start so an April
    # lookback never reaches into last September.
    end = season_mod.anchor_date()
    start = max(end - timedelta(days=days), season_mod.start_date())

    url = f"{BASE_URL}/schedule"
    params = {
        "teamId": team_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "sportId": 1,
        "gameType": game_types,
        "hydrate": "linescore,seriesStatus",
    }
    async with http.session(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    seen: set[int] = set()
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            # A suspended game that's resumed on a later date is listed on
            # both dates under the same gamePk — count it once.
            if not is_final(game) or game["gamePk"] in seen:
                continue
            seen.add(game["gamePk"])

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
                    # In a postseason game leagueRecord is the team's
                    # postseason record, not its season record — the series
                    # block below is the meaningful context there.
                    "record_after": us.get("leagueRecord") if game.get("gameType") == config.REGULAR_SEASON_GAME_TYPE else None,
                    "postseason": postseason_info(game),
                }
            )

    games.sort(key=lambda g: g["date"])
    return games


async def get_division_standings(team_id: int = config.TEAM_ID, season: int | None = None) -> list[dict]:
    """Fetch the standings for this team's own division, sorted by rank."""
    season = season or season_mod.current()
    url = f"{BASE_URL}/standings"
    params = {
        "leagueId": config.LEAGUE_ID,
        "season": season,
        "standingsTypes": "regularSeason",
    }
    async with http.session(timeout=10) as client:
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


async def get_league_records(season: int | None = None) -> dict[int, dict]:
    """Regular-season W-L for every MLB team (both leagues), keyed by team id."""
    season = season or season_mod.current()
    url = f"{BASE_URL}/standings"
    records: dict[int, dict] = {}

    async with http.session(timeout=10) as client:
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
                    record = team_record.get("leagueRecord", {})
                    records[team_record["team"]["id"]] = {
                        "wins": record.get("wins"),
                        "losses": record.get("losses"),
                        "pct": record.get("pct"),
                        "runs_scored": team_record.get("runsScored"),
                        "runs_allowed": team_record.get("runsAllowed"),
                    }

    return records


async def get_league_win_pcts(season: int | None = None) -> dict[int, float]:
    """Current win% for every MLB team (both leagues), keyed by team id."""
    season = season or season_mod.current()
    records = await get_league_records(season)
    return {tid: float(r["pct"]) for tid, r in records.items() if r.get("pct") is not None}


async def get_upcoming_games(
    team_id: int = config.TEAM_ID,
    count: int = 10,
    game_types: str = config.ALL_GAME_TYPES,
) -> list[dict]:
    """Fetch the next `count` not-yet-played games (postseason included),
    with probable pitchers."""
    # Eastern, not the server's UTC clock: after 8pm ET, UTC has already
    # rolled over to tomorrow, which would drop a late West Coast start
    # that hasn't begun yet from "upcoming."
    start = config.eastern_today()
    end = start + timedelta(days=30)  # generous window in case of postponements/gaps

    url = f"{BASE_URL}/schedule"
    params = {
        "teamId": team_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "sportId": 1,
        "gameType": game_types,
        "hydrate": "probablePitcher,seriesStatus",
    }
    async with http.session(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["abstractGameState"] not in ("Preview",):
                continue
            postseason = postseason_info(game)
            # An "if necessary" game the series never needed (e.g. Game 3
            # after a 2-0 sweep) can linger as Preview — never list it.
            if postseason and postseason["is_over"]:
                continue

            teams = game["teams"]
            is_home = teams["home"]["team"]["id"] == team_id
            us = teams["home"] if is_home else teams["away"]
            them = teams["away"] if is_home else teams["home"]
            them_record = them.get("leagueRecord", {})

            games.append(
                {
                    "game_pk": game["gamePk"],
                    "date": game["officialDate"],
                    "game_date_utc": game["gameDate"],
                    "start_time_tbd": bool(game["status"].get("startTimeTBD")),
                    "opponent": them["team"]["name"],
                    "opponent_id": them["team"]["id"],
                    "home_or_away": "home" if is_home else "away",
                    "opponent_record": {
                        "wins": them_record.get("wins"),
                        "losses": them_record.get("losses"),
                        "pct": them_record.get("pct"),
                    },
                    "us_probable_pitcher": (us.get("probablePitcher") or {}).get("fullName"),
                    "us_probable_pitcher_id": (us.get("probablePitcher") or {}).get("id"),
                    "opponent_probable_pitcher": (them.get("probablePitcher") or {}).get("fullName"),
                    "opponent_probable_pitcher_id": (them.get("probablePitcher") or {}).get("id"),
                    "venue": (game.get("venue") or {}).get("name"),
                    "game_number": game.get("gameNumber", 1),
                    "postseason": postseason,
                }
            )

    games.sort(key=lambda g: g["game_date_utc"])
    return games[:count]


async def get_wildcard_standings(team_id: int = config.TEAM_ID, season: int | None = None) -> list[dict]:
    """Fetch the Wild Card standings (division leaders excluded — they're
    already in via the division race, so this is specifically who's
    competing for the remaining playoff spots)."""
    season = season or season_mod.current()
    url = f"{BASE_URL}/standings"
    params = {
        "leagueId": config.LEAGUE_ID,
        "season": season,
        "standingsTypes": "wildCard",
    }
    async with http.session(timeout=10) as client:
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


async def get_postseason_games(team_id: int = config.TEAM_ID, season: int | None = None) -> list[dict]:
    """Every postseason game on this team's schedule for the season — played,
    live, or upcoming — oldest first. Empty until the team is actually in a
    postseason series (MLB only schedules clinched teams)."""
    season = season or season_mod.current()
    params = {
        "teamId": team_id,
        "season": season,
        "sportId": 1,
        "gameType": ",".join(config.POSTSEASON_GAME_TYPES),
        "hydrate": "linescore,seriesStatus",
    }
    async with http.session(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/schedule", params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    seen: set[int] = set()
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            coded = (game.get("status") or {}).get("codedGameState")
            if coded in ("D", "C"):  # postponed/cancelled — rescheduled copy appears separately
                continue
            if game["gamePk"] in seen:  # suspended + resumed: same gamePk on two dates
                continue
            seen.add(game["gamePk"])
            teams = game["teams"]
            is_home = teams["home"]["team"]["id"] == team_id
            us = teams["home"] if is_home else teams["away"]
            them = teams["away"] if is_home else teams["home"]
            games.append(
                {
                    "game_pk": game["gamePk"],
                    "date": game["officialDate"],
                    "game_date_utc": game["gameDate"],
                    "state": "final" if is_final(game) else game["status"]["abstractGameState"].lower(),
                    "opponent": them["team"]["name"],
                    "opponent_id": them["team"]["id"],
                    "home_or_away": "home" if is_home else "away",
                    "our_score": us.get("score"),
                    "their_score": them.get("score"),
                    "won": bool(us.get("isWinner")) if is_final(game) else None,
                    "postseason": postseason_info(game),
                }
            )
    games.sort(key=lambda g: g["game_date_utc"])
    return games
