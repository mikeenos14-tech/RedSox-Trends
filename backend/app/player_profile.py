from __future__ import annotations

import asyncio

import httpx

from . import config, player_highlight, player_stats, statcast

BASE_URL = "https://statsapi.mlb.com/api/v1"

# Home/Away and vs-Left/vs-Right — the same platoon-split concept already
# referenced elsewhere on the site (Front Office Analysis), just broken out
# per-player here instead of team-wide.
SPLIT_SIT_CODES = "h,a,vl,vr"
SPLIT_LABELS = {"h": "Home", "a": "Away", "vl": "vs LHP", "vr": "vs RHP"}
SPLIT_LABELS_PITCHING = {"h": "Home", "a": "Away", "vl": "vs LHB", "vr": "vs RHB"}

GAME_LOG_DISPLAY_COUNT = 20


async def _get_splits(person_id: int, group: str, season: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{BASE_URL}/people/{person_id}/stats",
            params={"stats": "statSplits", "group": group, "season": season, "sitCodes": SPLIT_SIT_CODES},
        )
        resp.raise_for_status()
        data = resp.json()

    stats = data.get("stats") or []
    raw_splits = stats[0].get("splits", []) if stats else []
    labels = SPLIT_LABELS_PITCHING if group == "pitching" else SPLIT_LABELS
    metrics_fn = player_stats._pitching_metrics if group == "pitching" else player_stats._hitting_metrics

    by_code = {s["split"]["code"]: s["stat"] for s in raw_splits}
    order = ["h", "a", "vl", "vr"]
    return [
        {"label": labels[code], "code": code, **metrics_fn(by_code[code])}
        for code in order
        if code in by_code
    ]


def _player_type(stat_lines: dict, position: str | None) -> str:
    if stat_lines.get("pitching_this_season") and not stat_lines.get("hitting_this_season"):
        return "pitcher"
    if position == "P":
        return "pitcher"
    return "hitter"


async def get_player_profile(person_id: int) -> dict | None:
    """Everything a dedicated player page needs, consolidated into one call:
    bio, season/career stat lines, recent game log, home/away and platoon
    splits, and (when the player qualifies) their Statcast percentile
    profile. Returns None if this player isn't on the current 40-man roster
    — the page only serves current Red Sox players, not league-wide lookup."""
    season = config.SEASON
    full_roster, active_roster = await asyncio.gather(
        player_stats.get_roster(roster_type="40Man"),
        player_stats.get_roster(roster_type="active"),
    )
    entry = next((e for e in full_roster if e["person"]["id"] == person_id), None)
    if entry is None:
        return None
    position = entry.get("position", {}).get("abbreviation")
    is_active = any(e["person"]["id"] == person_id for e in active_roster)

    bio, stat_lines = await asyncio.gather(
        player_highlight.get_person_bio(person_id),
        player_highlight.get_stat_lines(person_id, season),
    )
    player_type = _player_type(stat_lines, position)
    group = "pitching" if player_type == "pitcher" else "hitting"

    async with httpx.AsyncClient(timeout=20) as client:
        game_log_task = player_stats.get_game_log(client, person_id, season, group)
        splits_task = _get_splits(person_id, group, season)
        league_data_task = statcast.fetch_league_data()
        game_log, splits, league_data = await asyncio.gather(game_log_task, splits_task, league_data_task)

    statcast_profile = statcast.get_player_comparison_data(person_id, player_type, league_data)
    statcast_extra = statcast.get_player_extra_stats(person_id, player_type, league_data)

    bat_side = (bio.get("batSide") or {}).get("description")
    pitch_hand = (bio.get("pitchHand") or {}).get("description")
    birthplace_parts = [
        bio.get("birthCity"),
        bio.get("birthStateProvince") if bio.get("birthCountry") == "USA" else bio.get("birthCountry"),
    ]

    recent_games = list(reversed(game_log[-GAME_LOG_DISPLAY_COUNT:]))
    game_log_display = [
        {
            "date": g["date"],
            "opponent": (g.get("opponent") or {}).get("name"),
            "opponent_id": (g.get("opponent") or {}).get("id"),
            "home_or_away": "home" if g.get("isHome") else "away",
            "won": g.get("isWin"),
            "summary": g["stat"].get("summary"),
        }
        for g in recent_games
    ]

    return {
        "id": person_id,
        "name": bio.get("fullName"),
        "position": position,
        "player_type": player_type,
        "active": is_active,
        "jersey_number": bio.get("primaryNumber"),
        "age": bio.get("currentAge"),
        "birthplace": ", ".join(p for p in birthplace_parts if p) or None,
        "height": bio.get("height"),
        "weight": bio.get("weight"),
        "bat_side": bat_side,
        "pitch_hand": pitch_hand,
        "mlb_debut": bio.get("mlbDebutDate"),
        "verified_nickname": player_highlight.KNOWN_NICKNAMES.get(person_id),
        "headshot_url": f"https://midfield.mlbstatic.com/v1/people/{person_id}/spots/240",
        **stat_lines,
        "game_log": game_log_display,
        "splits": splits,
        "statcast": statcast_profile,
        "statcast_extra": statcast_extra,
    }
