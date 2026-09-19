from __future__ import annotations

from . import config, league_context, mlb_client, player_stats

# Season-long "top performer" credibility bar — deliberately higher than the
# recent-form thresholds elsewhere (MIN_RECENT_PA/MIN_RECENT_IP), since a
# handful of plate appearances or one relief outing can produce a flashy but
# meaningless season-stat line (e.g. a September call-up's 1.500 OPS in 3 ABs
# topping the list). This is about "who should I actually worry about,"
# not a complete reference.
MIN_SEASON_PA = 100
MIN_SEASON_IP = 20.0

TOP_HITTERS_COUNT = 5
TOP_PITCHERS_COUNT = 3


def _top_performers(roster_report: dict) -> dict:
    hitters = [h for h in roster_report["hitters"] if (h["season"].get("pa") or 0) >= MIN_SEASON_PA]
    pitchers = [p for p in roster_report["pitchers"] if (p["season"].get("ip") or 0) >= MIN_SEASON_IP]
    return {
        "hitters": hitters[:TOP_HITTERS_COUNT],
        "pitchers": pitchers[:TOP_PITCHERS_COUNT],
    }


async def get_team_profile(team_id: int, all_team_stats: dict) -> dict:
    """Everything a team-detail page needs, consolidated into one call:
    record/standing, where they rank league-wide (reusing the same
    already-fetched all-30-teams data Boston's own rank uses — no extra
    fetch), and their top performers by season OPS/ERA. Season series vs.
    the Red Sox and the next matchup are Red-Sox-perspective data the
    caller already has cached, so those are composed in by main.py rather
    than duplicated here.
    """
    standings = await mlb_client.get_team_standings(team_id=team_id)
    roster_report = await player_stats.get_full_roster_report(team_id=team_id)
    rank = league_context.compute_league_context(team_id, all_team_stats)

    league_record = standings.get("leagueRecord") or {}
    last_ten = next(
        (s for s in (standings.get("records") or {}).get("splitRecords", []) if s.get("type") == "lastTen"),
        None,
    )

    return {
        "id": team_id,
        "name": standings["team"]["name"],
        "wins": league_record.get("wins"),
        "losses": league_record.get("losses"),
        "pct": league_record.get("pct"),
        "division_rank": standings.get("divisionRank"),
        "games_back": standings.get("gamesBack"),
        "streak": (standings.get("streak") or {}).get("streakCode"),
        "last_10": f"{last_ten['wins']}-{last_ten['losses']}" if last_ten else None,
        "league_rank": {k: v for k, v in rank.items() if k != "run_diff_league_chart"},
        "top_performers": _top_performers(roster_report),
    }
