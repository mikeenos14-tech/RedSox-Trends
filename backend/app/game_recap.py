from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from . import config

BASE_URL = "https://statsapi.mlb.com/api/v1"
RSS_URL = "https://news.google.com/rss/search"


async def get_last_completed_game(team_id: int = config.TEAM_ID) -> dict | None:
    """Find the most recently completed regular-season game, with linescore
    and decisions (W/L/SV) hydrated. Looks back a generous window since the
    team can have off-days (including the All-Star break) between games."""
    end = date.today()
    start = end - timedelta(days=10)

    url = f"{BASE_URL}/schedule"
    params = {
        "teamId": team_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "sportId": 1,
        "gameType": "R",
        "hydrate": "linescore,decisions",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    completed = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game["status"]["detailedState"] == "Final":
                completed.append(game)

    if not completed:
        return None

    completed.sort(key=lambda g: g["gameDate"])
    return completed[-1]


def top_batting_lines(boxscore: dict, side: str, limit: int = 3) -> list[dict]:
    team = boxscore["teams"][side]
    lines = []
    for pid in team.get("batters", []):
        player = team["players"].get(f"ID{pid}")
        if not player:
            continue
        stats = player.get("stats", {}).get("batting", {})
        if not stats or stats.get("atBats", 0) == 0:
            continue
        lines.append(
            {
                "name": player["person"]["fullName"],
                "summary": stats.get("summary", ""),
                "hits": stats.get("hits", 0),
                "rbi": stats.get("rbi", 0),
                "home_runs": stats.get("homeRuns", 0),
            }
        )

    # Notable = drove in runs, went deep, or had a multi-hit game.
    lines.sort(key=lambda l: (l["rbi"], l["home_runs"], l["hits"]), reverse=True)
    return [l for l in lines if l["rbi"] or l["home_runs"] or l["hits"] >= 2][:limit]


def pitching_lines(boxscore: dict, side: str) -> list[dict]:
    team = boxscore["teams"][side]
    lines = []
    for pid in team.get("pitchers", []):
        player = team["players"].get(f"ID{pid}")
        if not player:
            continue
        stats = player.get("stats", {}).get("pitching", {})
        if not stats:
            continue
        lines.append(
            {
                "name": player["person"]["fullName"],
                "summary": stats.get("summary", ""),
                "note": stats.get("note"),
                "innings_pitched": stats.get("inningsPitched"),
                "earned_runs": stats.get("earnedRuns"),
                "strikeouts": stats.get("strikeOuts"),
            }
        )
    return lines


async def get_boxscore(game_pk: int) -> dict:
    url = f"{BASE_URL}/game/{game_pk}/boxscore"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _get_game_articles(opponent: str, game_date: str, limit: int = 6) -> list[dict]:
    """Search Google News RSS for coverage of this specific game, to ground
    the narrative recap in real reporting rather than the model's own
    (unreliable) memory of a specific game's story."""
    params = {
        "q": f'"Red Sox" "{opponent}" when:3d -intitle:Gameday',
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(RSS_URL, params=params)
        resp.raise_for_status()
        xml_text = resp.text

    root = ElementTree.fromstring(xml_text)
    articles = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else None

        if not title or not link:
            continue
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()

        articles.append({"title": title, "link": link, "source": source})
        if len(articles) >= limit:
            break

    return articles


async def get_last_game_recap_data(team_id: int = config.TEAM_ID) -> dict | None:
    """Build the full data payload for the 'Previous Game Recap' feature:
    box score facts (deterministic, from the MLB Stats API) plus real
    articles about the game (for the AI narrative to draw on). Returns None
    if no completed game is found in the lookback window (e.g. season hasn't
    started, or preseason)."""
    game = await get_last_completed_game(team_id)
    if game is None:
        return None

    game_pk = game["gamePk"]
    teams = game["teams"]
    is_home = teams["home"]["team"]["id"] == team_id
    us_side, them_side = ("home", "away") if is_home else ("away", "home")
    us = teams[us_side]
    them = teams[them_side]

    boxscore = await get_boxscore(game_pk)
    decisions = game.get("decisions", {})
    linescore = game.get("linescore", {})

    articles = await _get_game_articles(them["team"]["name"], game["officialDate"])

    return {
        "game_pk": game_pk,
        "date": game["officialDate"],
        "venue": (game.get("venue") or {}).get("name"),
        "opponent": them["team"]["name"],
        "home_or_away": "home" if is_home else "away",
        "won": bool(us.get("isWinner")),
        "our_score": us.get("score"),
        "their_score": them.get("score"),
        "record_after": {
            "wins": us.get("leagueRecord", {}).get("wins"),
            "losses": us.get("leagueRecord", {}).get("losses"),
        },
        "line_score": {
            # A team that's already ahead doesn't bat in the bottom of the
            # last inning, so that half-inning's "runs" key is simply absent
            # rather than 0 — default it explicitly.
            "innings": [
                {
                    "num": inning["num"],
                    "us": inning[us_side].get("runs", 0),
                    "them": inning[them_side].get("runs", 0),
                }
                for inning in linescore.get("innings", [])
            ],
            "totals": {
                "us": {
                    "runs": linescore.get("teams", {}).get(us_side, {}).get("runs"),
                    "hits": linescore.get("teams", {}).get(us_side, {}).get("hits"),
                    "errors": linescore.get("teams", {}).get(us_side, {}).get("errors"),
                },
                "them": {
                    "runs": linescore.get("teams", {}).get(them_side, {}).get("runs"),
                    "hits": linescore.get("teams", {}).get(them_side, {}).get("hits"),
                    "errors": linescore.get("teams", {}).get(them_side, {}).get("errors"),
                },
            },
        },
        "winning_pitcher": (decisions.get("winner") or {}).get("fullName"),
        "losing_pitcher": (decisions.get("loser") or {}).get("fullName"),
        "save_pitcher": (decisions.get("save") or {}).get("fullName"),
        "top_performers": {
            "us": top_batting_lines(boxscore, us_side),
            "them": top_batting_lines(boxscore, them_side),
        },
        "pitching": {
            "us": pitching_lines(boxscore, us_side),
            "them": pitching_lines(boxscore, them_side),
        },
        "articles": articles,
    }
