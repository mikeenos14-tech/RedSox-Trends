from __future__ import annotations

import asyncio
from datetime import datetime

from . import config, game_recap, mlb_client, player_highlight, player_stats

LOOKBACK_DAYS = 5


def _innings_to_outs(ip: str | None) -> int:
    if not ip:
        return 0
    whole, _, frac = ip.partition(".")
    try:
        return int(whole or 0) * 3 + int(frac or 0)
    except ValueError:
        return 0


# Transparent, conventional workload rules — not official (MLB publishes no
# availability feed), but the same rough reads beat writers use:
HEAVY_OUTING_PITCHES = 30  # 30+ pitches yesterday usually means a day off
STATUS_USED_TODAY = "Used today"
STATUS_UNAVAILABLE = "Likely unavailable"
STATUS_LIMITED = "Limited"
STATUS_AVAILABLE = "Available"


def availability(outings_by_days_ago: dict[int, dict]) -> str:
    """Status from a reliever's recent outings, keyed by days ago (0 = today).
    - pitched today → used today
    - back-to-back days ending yesterday, 3 outings in the last 4 days, or a
      30+ pitch outing yesterday → likely unavailable
    - any other outing yesterday → limited
    - otherwise → available"""
    if 0 in outings_by_days_ago:
        return STATUS_USED_TODAY
    yesterday = outings_by_days_ago.get(1)
    if yesterday:
        if 2 in outings_by_days_ago:
            return STATUS_UNAVAILABLE
        if (yesterday.get("pitches") or 0) >= HEAVY_OUTING_PITCHES:
            return STATUS_UNAVAILABLE
    if sum(1 for d in outings_by_days_ago if d <= 3) >= 3:
        return STATUS_UNAVAILABLE
    if yesterday:
        return STATUS_LIMITED
    return STATUS_AVAILABLE


async def get_bullpen_report(team_id: int = config.TEAM_ID) -> list[dict]:
    """Availability read for the whole active bullpen — every reliever on the
    active roster, including ones who haven't pitched lately (a fully rested
    closer is the most important row, not a missing one). This is a
    heuristic, not official bullpen-management data; see availability()."""
    # Postseason games included: October workload is exactly what decides
    # who's available tonight, and a regular-season-only lookback would
    # show the whole bullpen as fully rested mid-series.
    games = await mlb_client.get_recent_games(team_id=team_id, days=LOOKBACK_DAYS, game_types=config.ALL_GAME_TYPES)
    if not games:
        return []

    boxscores, active_roster = await asyncio.gather(
        asyncio.gather(*[game_recap.get_boxscore(g["game_pk"]) for g in games]),
        player_stats.get_roster(roster_type="active", team_id=team_id),
    )
    active_pitchers = {
        entry["person"]["id"]: entry["person"]["fullName"]
        for entry in active_roster
        if (entry.get("position") or {}).get("abbreviation") in ("P", "TWP")
    }
    # Relievers = active pitchers who mostly relieve this season. Starters
    # are left out: their availability is the rotation, not the bullpen.
    people = await player_stats._get_people_with_stats(list(active_pitchers))
    relievers = set()
    for person in people:
        season_pitch = player_stats._first_split(person, "season", "pitching") or {}
        games_pitched = season_pitch.get("gamesPitched") or 0
        if games_pitched == 0 or (season_pitch.get("gamesStarted") or 0) < games_pitched / 2:
            relievers.add(person["id"])

    appearances: dict[int, list[dict]] = {pid: [] for pid in relievers}
    for game, boxscore in zip(games, boxscores):
        side = game["home_or_away"]
        team_box = boxscore["teams"][side]
        for pid in team_box.get("pitchers", []):
            if pid not in relievers:
                continue
            player = team_box["players"].get(f"ID{pid}")
            stats = (player or {}).get("stats", {}).get("pitching", {})
            if not stats:
                continue
            appearances[pid].append(
                {
                    "date": game["date"],
                    "innings_pitched": stats.get("inningsPitched"),
                    "pitches": stats.get("numberOfPitches"),
                }
            )

    # Eastern, not server-local: the server runs on UTC, which has already
    # rolled to "tomorrow" for several hours every evening while it's still
    # today in Boston — using the server's raw clock here would misjudge a
    # pitcher who threw earlier tonight as having a full day of rest.
    today = player_highlight.eastern_today()
    report = []
    for pid in relievers:
        outings = sorted(appearances[pid], key=lambda o: o["date"])
        by_days_ago: dict[int, dict] = {}
        for o in outings:
            days_ago = (today - datetime.strptime(o["date"], "%Y-%m-%d").date()).days
            prior = by_days_ago.get(days_ago)
            # Doubleheader: combine both outings' pitches for that day.
            by_days_ago[days_ago] = (
                {**o, "pitches": (prior.get("pitches") or 0) + (o.get("pitches") or 0)} if prior else o
            )
        last = outings[-1] if outings else None
        report.append(
            {
                "player_id": pid,
                "name": active_pitchers[pid],
                "last_pitched": last["date"] if last else None,
                "days_rest": (today - datetime.strptime(last["date"], "%Y-%m-%d").date()).days if last else None,
                "last_outing": (
                    (f"{last['innings_pitched']} IP, {last['pitches']} pitches" if last["pitches"] else f"{last['innings_pitched']} IP")
                    if last
                    else None
                ),
                "appearances_last_3_days": sum(1 for d in by_days_ago if d <= 2),
                "pitches_last_3_days": sum((o.get("pitches") or 0) for d, o in by_days_ago.items() if d <= 2),
                "status": availability(by_days_ago),
            }
        )

    order = {STATUS_USED_TODAY: 0, STATUS_UNAVAILABLE: 1, STATUS_LIMITED: 2, STATUS_AVAILABLE: 3}
    report.sort(key=lambda r: (order[r["status"]], r["days_rest"] if r["days_rest"] is not None else 99, r["name"]))
    return report
