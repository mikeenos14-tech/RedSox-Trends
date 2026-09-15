from __future__ import annotations

import asyncio
import csv
import io
import json
import re

import httpx

from . import config, player_stats

PERCENTILE_URL = "https://baseballsavant.mlb.com/leaderboard/percentile-rankings"
CUSTOM_URL = "https://baseballsavant.mlb.com/leaderboard/custom"

# Baseball Savant has no official public API — this hits the same CSV/JSON
# export endpoints its own leaderboard pages use client-side (the pattern
# the community's `pybaseball` library also relies on). No key required, but
# it wants a browser-like User-Agent or it 403s.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StatSoxDashboard/1.0)"}

_LEADERBOARD_RE = re.compile(r"var leaderboard_data = (\[.*?\]);", re.DOTALL)

# (percentile field on the leaderboard payload, matching field on the custom
# CSV export, display label, value formatter)
HITTER_STATS = [
    ("percent_rank_xwoba", "xwoba", "xwOBA", lambda v: f"{v:.3f}".lstrip("0")),
    ("percent_rank_barrel_batted_rate", "barrel_batted_rate", "Barrel%", lambda v: f"{v:.1f}%"),
    ("percent_rank_hard_hit_percent", "hard_hit_percent", "Hard-Hit%", lambda v: f"{v:.1f}%"),
    ("percent_rank_exit_velocity_avg", "exit_velocity_avg", "Avg Exit Velo", lambda v: f"{v:.1f} mph"),
    ("percent_rank_whiff_percent", "whiff_percent", "Whiff%", lambda v: f"{v:.1f}%"),
    ("percent_speed_order", "sprint_speed", "Sprint Speed", lambda v: f"{v:.1f} ft/sec"),
]

PITCHER_STATS = [
    ("percent_rank_xera", "xera", "xERA", lambda v: f"{v:.2f}"),
    ("percent_rank_whiff_percent", "whiff_percent", "Whiff%", lambda v: f"{v:.1f}%"),
    ("percent_rank_hard_hit_percent", "hard_hit_percent", "Hard-Hit% Allowed", lambda v: f"{v:.1f}%"),
    ("percent_rank_k_percent", "k_percent", "K%", lambda v: f"{v:.1f}%"),
    ("percent_rank_fastball_velo", "fastball_avg_speed", "Fastball Velo", lambda v: f"{v:.1f} mph"),
]

# Headline stats worth a league-wide "who leads MLB" callout.
# (custom CSV field, label, formatter, higher_is_better)
HITTER_LEADER_STATS = [
    ("xwoba", "xwOBA", lambda v: f"{v:.3f}".lstrip("0"), True),
    ("barrel_batted_rate", "Barrel%", lambda v: f"{v:.1f}%", True),
]
PITCHER_LEADER_STATS = [
    ("xera", "xERA", lambda v: f"{v:.2f}", False),
    ("fastball_avg_speed", "Fastball Velo", lambda v: f"{v:.1f} mph", True),
]


async def _fetch_percentile_rankings(player_type: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        resp = await client.get(PERCENTILE_URL, params={"year": config.SEASON, "type": player_type})
        resp.raise_for_status()
        html = resp.text

    # Savant renders this leaderboard client-side; the full dataset (every
    # qualifying player, pre-computed percentiles included) ships inline as
    # a JS variable in the page rather than from a separate JSON endpoint.
    match = _LEADERBOARD_RE.search(html)
    if not match:
        return []
    return json.loads(match.group(1))


async def _fetch_custom_leaderboard(player_type: str, selections: list[str]) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        resp = await client.get(
            CUSTOM_URL,
            params={
                "year": config.SEASON,
                "type": player_type,
                "min": 1,  # no min PA/IP filter — match percentile-rankings' broader inclusion
                "selections": ",".join(selections),
                "csv": "true",
            },
        )
        resp.raise_for_status()
        text = resp.text.lstrip("﻿")

    rows: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        pid = row.get("player_id")
        if not pid:
            continue
        parsed = {}
        for key in selections:
            raw = row.get(key)
            if raw in (None, ""):
                continue
            try:
                parsed[key] = float(raw)
            except ValueError:
                continue
        rows[pid] = parsed
    return rows


def _display_name(savant_name: str) -> str:
    # Savant formats names as "Last, First" — flip to "First Last".
    parts = savant_name.split(", ", 1)
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else savant_name


# A bench player with a single qualifying metric (e.g. only Sprint Speed,
# because that's the one thing measurable in limited action) can land a
# 100th-percentile score there and otherwise nothing — averaging that one
# number would rank them above everyday players with a full, more modest
# stat line. Require a real spread of qualifying metrics before a player
# counts as a meaningful comparison point here.
MIN_STATS_FOR_INCLUSION = 3


def _build_player_entries(
    roster_ids: set[str],
    percentile_rows: list[dict],
    custom_values: dict[str, dict],
    stat_defs: list[tuple],
) -> list[dict]:
    entries = []
    for row in percentile_rows:
        pid = row.get("player_id")
        if pid not in roster_ids:
            continue

        stats = {}
        for pct_field, custom_field, label, fmt in stat_defs:
            percentile = row.get(pct_field)
            if percentile is None:
                continue
            value = (custom_values.get(pid) or {}).get(custom_field)
            stats[label] = {
                "percentile": int(percentile),
                "value": fmt(value) if value is not None else None,
            }

        if len(stats) < MIN_STATS_FOR_INCLUSION:
            continue

        entries.append(
            {
                "player_id": int(pid),
                "name": _display_name(row["player_name"]),
                "stats": stats,
            }
        )

    def avg_percentile(entry: dict) -> float:
        vals = [s["percentile"] for s in entry["stats"].values()]
        return sum(vals) / len(vals) if vals else 0

    entries.sort(key=avg_percentile, reverse=True)
    return entries


def _build_league_leaders(
    percentile_rows: list[dict],
    custom_values: dict[str, dict],
    leader_defs: list[tuple],
    limit: int = 5,
) -> dict[str, list[dict]]:
    team_by_id = {row["player_id"]: row["team_name"] for row in percentile_rows}
    name_by_id = {row["player_id"]: _display_name(row["player_name"]) for row in percentile_rows}

    leaders: dict[str, list[dict]] = {}
    for field, label, fmt, higher_is_better in leader_defs:
        ranked = [(pid, vals[field]) for pid, vals in custom_values.items() if field in vals and pid in name_by_id]
        ranked.sort(key=lambda t: t[1], reverse=higher_is_better)
        leaders[label] = [
            {
                "name": name_by_id[pid],
                "team": team_by_id.get(pid, "?"),
                "value": fmt(val),
                "is_red_sox": team_by_id.get(pid) == "Red Sox",
            }
            for pid, val in ranked[:limit]
        ]
    return leaders


def _team_snapshot(entries: list[dict]) -> dict[str, float]:
    totals: dict[str, list[int]] = {}
    for entry in entries:
        for label, stat in entry["stats"].items():
            totals.setdefault(label, []).append(stat["percentile"])
    return {label: round(sum(vals) / len(vals)) for label, vals in totals.items()}


async def get_statcast_report() -> dict:
    roster = await player_stats.get_roster()
    roster_ids = {str(entry["person"]["id"]) for entry in roster}

    hitter_selections = [c for _, c, _, _ in HITTER_STATS]
    pitcher_selections = [c for _, c, _, _ in PITCHER_STATS]

    (
        percentile_batters,
        percentile_pitchers,
        custom_batters,
        custom_pitchers,
    ) = await asyncio.gather(
        _fetch_percentile_rankings("batter"),
        _fetch_percentile_rankings("pitcher"),
        _fetch_custom_leaderboard("batter", hitter_selections),
        _fetch_custom_leaderboard("pitcher", pitcher_selections),
    )

    hitters = _build_player_entries(roster_ids, percentile_batters, custom_batters, HITTER_STATS)
    pitchers = _build_player_entries(roster_ids, percentile_pitchers, custom_pitchers, PITCHER_STATS)

    return {
        "hitters": hitters,
        "pitchers": pitchers,
        "team_snapshot": {
            "hitters": _team_snapshot(hitters),
            "pitchers": _team_snapshot(pitchers),
        },
        "league_leaders": {
            "hitters": _build_league_leaders(percentile_batters, custom_batters, HITTER_LEADER_STATS),
            "pitchers": _build_league_leaders(percentile_pitchers, custom_pitchers, PITCHER_LEADER_STATS),
        },
    }
