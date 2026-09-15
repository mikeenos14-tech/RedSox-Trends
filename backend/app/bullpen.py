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


async def get_bullpen_report(team_id: int = config.TEAM_ID) -> list[dict]:
    """Build a simple availability read for every reliever who's appeared
    recently: last time they pitched, how many times in the last 3 days, and
    a rough "likely available tonight" flag. This is a heuristic, not
    official bullpen-management data — MLB doesn't publish an availability
    feed — but back-to-back-day usage is a reasonable, transparent proxy."""
    games = await mlb_client.get_recent_games(team_id=team_id, days=LOOKBACK_DAYS)
    if not games:
        return []

    boxscores = await asyncio.gather(*[game_recap.get_boxscore(g["game_pk"]) for g in games])

    roster = await player_stats.get_roster()
    pitcher_ids = {
        entry["person"]["id"]
        for entry in roster
        if (entry.get("position") or {}).get("abbreviation") == "P"
    }

    appearances: dict[int, list[dict]] = {}
    for game, boxscore in zip(games, boxscores):
        side = game["home_or_away"]
        team_box = boxscore["teams"][side]
        for pid in team_box.get("pitchers", []):
            if pid not in pitcher_ids:
                continue
            player = team_box["players"].get(f"ID{pid}")
            if not player:
                continue
            stats = player.get("stats", {}).get("pitching", {})
            if not stats:
                continue
            # A starter's outing doesn't affect bullpen availability the way
            # a reliever's does — exclude anyone who started that game.
            if stats.get("gamesStarted"):
                continue
            appearances.setdefault(pid, []).append(
                {
                    "date": game["date"],
                    "name": player["person"]["fullName"],
                    "innings_pitched": stats.get("inningsPitched"),
                    "pitches": stats.get("numberOfPitches"),
                    "outs": _innings_to_outs(stats.get("inningsPitched")),
                }
            )

    # Eastern, not server-local: the server runs on UTC, which has already
    # rolled to "tomorrow" for several hours every evening while it's still
    # today in Boston — using the server's raw clock here would misjudge a
    # pitcher who threw earlier tonight as having a full day of rest.
    today = player_highlight.eastern_today()
    report = []
    for pid, outings in appearances.items():
        outings.sort(key=lambda o: o["date"])
        last = outings[-1]
        last_date = datetime.strptime(last["date"], "%Y-%m-%d").date()
        days_rest = (today - last_date).days
        appearances_last_3_days = sum(
            1 for o in outings if (today - datetime.strptime(o["date"], "%Y-%m-%d").date()).days <= 2
        )

        # Rough, transparent heuristic: pitched yesterday or today, or three
        # appearances in three days, reads as unlikely to be available.
        likely_available = not (days_rest <= 0 or appearances_last_3_days >= 3)

        report.append(
            {
                "player_id": pid,
                "name": last["name"],
                "last_pitched": last["date"],
                "days_rest": days_rest,
                "last_outing": f"{last['innings_pitched']} IP, {last['pitches']} pitches" if last["pitches"] else f"{last['innings_pitched']} IP",
                "appearances_last_3_days": appearances_last_3_days,
                "likely_available": likely_available,
            }
        )

    report.sort(key=lambda r: (r["days_rest"], -r["appearances_last_3_days"]))
    return report
