"""The offseason Home: how the season ended, the numbers that defined it,
the best individual seasons, and when baseball comes back.

Shown only once the team's season is actually over — eliminated, champion,
or no postseason at all once the regular season has ended — and until the
next season's schedule brings the next-game card back.
"""
from __future__ import annotations

from datetime import date

from . import config, mlb_client, trends
from . import http
from . import season as season_mod

BASE_URL = http.MLB_API

# "Best seasons" qualifiers: real everyday / rotation / bullpen workloads, so
# a September call-up's 40 hot plate appearances can't top the list.
MIN_PA_HITTER = 300
MIN_IP_STARTER = 100
MIN_IP_RELIEVER = 40


def season_is_over(postseason: dict | None, has_upcoming_games: bool, regular_season_over: bool) -> bool:
    if has_upcoming_games:
        return False
    if postseason:
        return postseason["phase"] in ("eliminated", "won_world_series")
    return regular_season_over  # no postseason games at all: missed the playoffs


def postseason_path(postseason_games: list[dict], team_id: int = config.TEAM_ID) -> list[dict]:
    """Each postseason series played, in order, with the result — e.g. won
    the ALWC 2-1, lost the ALDS 1-3 to the Yankees."""
    series: dict[str, dict] = {}
    for g in postseason_games:
        if g["state"] != "final":
            continue
        ps = g["postseason"]
        entry = series.setdefault(
            ps["series"],
            {"series": ps["series"], "abbreviation": ps["abbreviation"], "game_type": ps["game_type"],
             "opponent": g["opponent"], "wins": 0, "losses": 0, "won": None},
        )
        entry["wins" if g["won"] else "losses"] += 1
        if ps["is_over"]:
            entry["won"] = ps["winning_team_id"] == team_id
    return list(series.values())


def outcome_text(path: list[dict]) -> str:
    if not path:
        return "Missed the postseason."
    last = path[-1]
    if last["won"] and last["game_type"] == "W":
        return "World Series champions."
    if last["won"] is False:
        return f"Eliminated in the {last['series']} by the {last['opponent']}, {last['wins']}-{last['losses']}."
    return f"Won the {last['series']}, {last['wins']}-{last['losses']}."


def best_seasons(roster: dict) -> dict:
    """Top seasons on the (park-adjusted) roster report."""
    hitters = sorted(
        (h for h in roster.get("hitters", []) if (h["season"].get("pa") or 0) >= MIN_PA_HITTER and h["season"].get("ops_plus") is not None),
        key=lambda h: h["season"]["ops_plus"],
        reverse=True,
    )[:3]
    starters = sorted(
        (p for p in roster.get("pitchers", []) if p["role"] == "SP" and (p["season"].get("ip") or 0) >= MIN_IP_STARTER and p["season"].get("era_minus") is not None),
        key=lambda p: p["season"]["era_minus"],
    )[:2]
    relievers = sorted(
        (p for p in roster.get("pitchers", []) if p["role"] == "RP" and (p["season"].get("ip") or 0) >= MIN_IP_RELIEVER and p["season"].get("era_minus") is not None),
        key=lambda p: p["season"]["era_minus"],
    )[:1]

    def hitter(h):
        s = h["season"]
        return {"id": h["id"], "name": h["name"], "position": h["position"], "ops_plus": s["ops_plus"], "ops": s["ops"], "hr": s["hr"], "pa": s["pa"]}

    def pitcher(p):
        s = p["season"]
        return {"id": p["id"], "name": p["name"], "role": p["role"], "era_minus": s["era_minus"], "era": s["era"], "ip": s["ip_display"], "fip": s["fip"]}

    return {"hitters": [hitter(h) for h in hitters], "pitchers": [pitcher(p) for p in starters + relievers]}


async def next_season_openers(team_id: int = config.TEAM_ID) -> dict | None:
    """Opening Day and the Fenway home opener from next season's published
    schedule; None until MLB publishes it."""
    next_season = season_mod.current() + 1
    async with http.session(timeout=10) as client:
        resp = await client.get(
            f"{BASE_URL}/schedule",
            params={"teamId": team_id, "season": next_season, "sportId": 1, "gameType": "R", "startDate": f"{next_season}-02-01", "endDate": f"{next_season}-05-15"},
        )
        resp.raise_for_status()
        data = resp.json()
    games = sorted((g for d in data.get("dates", []) for g in d.get("games", [])), key=lambda g: g["gameDate"])
    if not games:
        return None

    def describe(g):
        home = g["teams"]["home"]["team"]["id"] == team_id
        opp = g["teams"]["away" if home else "home"]["team"]
        return {
            "date": g["officialDate"],
            "game_date_utc": g["gameDate"],
            "home_or_away": "home" if home else "away",
            "opponent": opp["name"],
            "opponent_id": opp["id"],
            "venue": (g.get("venue") or {}).get("name"),
        }

    home_opener = next((g for g in games if g["teams"]["home"]["team"]["id"] == team_id), None)
    return {"season": next_season, "opening_day": describe(games[0]), "home_opener": describe(home_opener) if home_opener else None}


def days_until(iso_date: str, today: date | None = None) -> int:
    return (date.fromisoformat(iso_date) - (today or config.eastern_today())).days


async def check() -> tuple[bool, dict, list[dict]]:
    """Cheap first step (three schedule/standings requests): is the season
    over? Returns (over, standings, postseason games) so the heavy inputs
    for the review are only fetched when it will actually be shown."""
    standings, postseason_games, upcoming = (
        await mlb_client.get_team_standings(),
        await mlb_client.get_postseason_games(),
        await mlb_client.get_upcoming_games(),
    )
    postseason = trends.summarize_postseason(postseason_games, config.TEAM_ID)
    over = season_is_over(postseason, bool(upcoming), season_mod.regular_season_over())
    return over, standings, postseason_games


async def build(standings: dict, postseason_games: list[dict], league_ctx: dict, adjusted_roster: dict) -> dict:
    record = standings.get("leagueRecord") or {}
    runs_scored, runs_allowed = standings.get("runsScored"), standings.get("runsAllowed")
    path = postseason_path(postseason_games)
    try:
        openers = await next_season_openers()
    except Exception:  # noqa: BLE001 — the countdown is a nicety; the review stands without it
        openers = None
    if openers:
        openers["days_until_opening_day"] = days_until(openers["opening_day"]["date"])

    return {
        "season_over": True,
        "season": season_mod.current(),
        "record": {"wins": record.get("wins"), "losses": record.get("losses"), "pct": record.get("pct")},
        "division_rank": standings.get("divisionRank"),
        "games_back": standings.get("gamesBack"),
        "run_differential": (runs_scored or 0) - (runs_allowed or 0),
        "outcome": outcome_text(path),
        "postseason_path": path,
        "team_ops_plus": league_ctx.get("team_ops_plus"),
        "team_era_minus": league_ctx.get("team_era_minus"),
        "best_seasons": best_seasons(adjusted_roster),
        "next_season": openers,
    }
