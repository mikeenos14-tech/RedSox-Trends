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
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FenwayAlmanacDashboard/1.0)"}

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

# Every signature stat, available as a league-wide "who leads MLB"
# leaderboard — not just the two flagship ones shown by default.
# (custom CSV field, label, formatter, higher_is_better)
HITTER_LEADER_STATS = [
    ("xwoba", "xwOBA", lambda v: f"{v:.3f}".lstrip("0"), True),
    ("barrel_batted_rate", "Barrel%", lambda v: f"{v:.1f}%", True),
    ("hard_hit_percent", "Hard-Hit%", lambda v: f"{v:.1f}%", True),
    ("exit_velocity_avg", "Avg Exit Velo", lambda v: f"{v:.1f} mph", True),
    ("sprint_speed", "Sprint Speed", lambda v: f"{v:.1f} ft/sec", True),
    ("whiff_percent", "Whiff%", lambda v: f"{v:.1f}%", False),
]
PITCHER_LEADER_STATS = [
    ("xera", "xERA", lambda v: f"{v:.2f}", False),
    ("whiff_percent", "Whiff%", lambda v: f"{v:.1f}%", True),
    ("hard_hit_percent", "Hard-Hit% Allowed", lambda v: f"{v:.1f}%", False),
    ("k_percent", "K%", lambda v: f"{v:.1f}%", True),
    ("fastball_avg_speed", "Fastball Velo", lambda v: f"{v:.1f} mph", True),
]

# The two shown by default in the flagship "League Leaders" grid — the rest
# are only surfaced through the "explore any leaderboard" picker.
FLAGSHIP_HITTER_LEADER_LABELS = ["xwOBA", "Barrel%"]
FLAGSHIP_PITCHER_LEADER_LABELS = ["xERA", "Fastball Velo"]

# Every metric on a player's page beyond the flagship few above, for the
# "explore any Statcast metric" picker — no raw value/formatter needed since
# these aren't fetched from the custom leaderboard (that's a separate,
# unverified field-name mapping per stat, not worth fetching for a picker
# that's mostly used a few times per visit); the percentile alone, which
# comes free with the same percentile-rankings fetch every other Statcast
# feature already uses, is what answers "how good is this, relatively."
# Deliberately excludes bat-tracking (swing_speed, swing_length,
# squared_up_swing, vertical_swing_path, attack_angle) and pitch-design
# internals (cu_spin, fastball_spin, fastball_extension) — real Statcast
# fields, but not something a casual dropdown label can explain on its own.
HITTER_EXTRA_STATS = [
    ("percent_rank_ba", "AVG"),
    ("percent_rank_obp", "OBP"),
    ("percent_rank_slg", "SLG"),
    ("percent_rank_woba", "wOBA"),
    ("percent_rank_iso", "ISO"),
    ("percent_rank_babip", "BABIP"),
    ("percent_rank_bb_percent", "Walk%"),
    ("percent_rank_k_percent", "Strikeout%"),
    ("percent_rank_chase_percent", "Chase%"),
    ("percent_rank_xba", "xBA"),
    ("percent_rank_xslg", "xSLG"),
    ("percent_rank_xobp", "xOBP"),
    ("percent_rank_xiso", "xISO"),
    ("percent_rank_exit_velocity_max", "Max Exit Velo"),
    ("percent_rank_launch_angle_avg", "Avg Launch Angle"),
    ("percent_rank_oaa", "Outs Above Average"),
    ("percent_rank_jump", "First-Step Jump"),
    ("percent_rank_arm_overall", "Arm Strength"),
    ("percent_rank_arm_max", "Max Arm Strength"),
    ("percent_rank_pop_2b", "Pop Time to 2B"),
    ("percent_rank_framing", "Framing"),
]

PITCHER_EXTRA_STATS = [
    ("percent_rank_ba", "AVG Against"),
    ("percent_rank_obp", "OBP Against"),
    ("percent_rank_slg", "SLG Against"),
    ("percent_rank_woba", "wOBA Against"),
    ("percent_rank_iso", "ISO Against"),
    ("percent_rank_babip", "BABIP Against"),
    ("percent_rank_bb_percent", "Walk%"),
    ("percent_rank_chase_percent", "Chase%"),
    ("percent_rank_xba", "xBA Against"),
    ("percent_rank_xslg", "xSLG Against"),
    ("percent_rank_xobp", "xOBP Against"),
    ("percent_rank_xiso", "xISO Against"),
    ("percent_rank_exit_velocity_max", "Max Exit Velo Allowed"),
    ("percent_rank_barrel_batted_rate", "Barrel% Allowed"),
    ("percent_rank_oaa", "Outs Above Average"),
]


async def fetch_percentile_rankings(player_type: str) -> list[dict]:
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


async def fetch_custom_leaderboard(player_type: str, selections: list[str]) -> dict[str, dict]:
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


def display_name(savant_name: str) -> str:
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


def build_stats_for_row(row: dict, custom_values: dict[str, dict], stat_defs: list[tuple]) -> dict:
    pid = row.get("player_id")
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
    return stats


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

        stats = build_stats_for_row(row, custom_values, stat_defs)
        if len(stats) < MIN_STATS_FOR_INCLUSION:
            continue

        entries.append(
            {
                "player_id": int(pid),
                "name": display_name(row["player_name"]),
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
    name_by_id = {row["player_id"]: display_name(row["player_name"]) for row in percentile_rows}

    leaders: dict[str, list[dict]] = {}
    for field, label, fmt, higher_is_better in leader_defs:
        ranked = [(pid, vals[field]) for pid, vals in custom_values.items() if field in vals and pid in name_by_id]
        ranked.sort(key=lambda t: t[1], reverse=higher_is_better)
        leaders[label] = [
            {
                "id": int(pid),
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


async def fetch_league_data() -> dict:
    """Every Savant fetch needed across the team report, player search, and
    player comparison — grouped into one call so a day-scoped cache upstream
    only has to hit Savant once, regardless of which of those three features
    is used first."""
    hitter_selections = [c for _, c, _, _ in HITTER_STATS]
    pitcher_selections = [c for _, c, _, _ in PITCHER_STATS]

    (
        percentile_batters,
        percentile_pitchers,
        custom_batters,
        custom_pitchers,
    ) = await asyncio.gather(
        fetch_percentile_rankings("batter"),
        fetch_percentile_rankings("pitcher"),
        fetch_custom_leaderboard("batter", hitter_selections),
        fetch_custom_leaderboard("pitcher", pitcher_selections),
    )

    return {
        "percentile_batters": percentile_batters,
        "percentile_pitchers": percentile_pitchers,
        "custom_batters": custom_batters,
        "custom_pitchers": custom_pitchers,
    }


async def get_statcast_report(league_data: dict) -> dict:
    roster = await player_stats.get_roster()
    roster_ids = {str(entry["person"]["id"]) for entry in roster}

    percentile_batters = league_data["percentile_batters"]
    percentile_pitchers = league_data["percentile_pitchers"]
    custom_batters = league_data["custom_batters"]
    custom_pitchers = league_data["custom_pitchers"]

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
        "flagship_leader_labels": {
            "hitters": FLAGSHIP_HITTER_LEADER_LABELS,
            "pitchers": FLAGSHIP_PITCHER_LEADER_LABELS,
        },
    }


def search_players(query: str, league_data: dict) -> list[dict]:
    """Name-substring search across this year's qualifying batters and
    pitchers, for the comparison tool's player picker."""
    query = query.strip().lower()
    if not query:
        return []

    matches = []
    seen: set[tuple[str, str]] = set()
    sources = (
        ("hitter", league_data["percentile_batters"]),
        ("pitcher", league_data["percentile_pitchers"]),
    )
    for player_type, rows in sources:
        for row in rows:
            name = display_name(row["player_name"])
            pid = row.get("player_id")
            key = (pid, player_type)
            if query not in name.lower() or key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "player_id": int(pid),
                    "name": name,
                    "team": row.get("team_name", "?"),
                    "type": player_type,
                }
            )

    matches.sort(key=lambda m: m["name"])
    return matches[:20]


def get_player_comparison_data(player_id: int, player_type: str, league_data: dict) -> dict | None:
    """A single player's Statcast percentile profile, for the head-to-head
    comparison tool. Unlike the team report, there's no MIN_STATS_FOR_INCLUSION
    gate here — a specific player the user asked to see should show whatever
    stats are available, even if sparse."""
    stat_defs = HITTER_STATS if player_type == "hitter" else PITCHER_STATS
    percentile_rows = league_data["percentile_batters"] if player_type == "hitter" else league_data["percentile_pitchers"]
    custom_values = league_data["custom_batters"] if player_type == "hitter" else league_data["custom_pitchers"]

    pid = str(player_id)
    row = next((r for r in percentile_rows if r.get("player_id") == pid), None)
    if row is None:
        return None

    stats = build_stats_for_row(row, custom_values, stat_defs)
    return {
        "player_id": player_id,
        "name": display_name(row["player_name"]),
        "team": row.get("team_name", "?"),
        "type": player_type,
        "stats": stats,
    }


def get_player_extra_stats(player_id: int, player_type: str, league_data: dict) -> dict:
    """Every Statcast metric beyond the flagship few, for a player's 'explore
    another metric' picker — percentile only (see HITTER_EXTRA_STATS), and
    only the ones actually populated for this specific player (a corner
    outfielder simply won't have Pop Time to 2B, a pitcher won't have most
    hitting metrics — this filters naturally rather than needing to know
    each metric's real-world applicability in advance)."""
    extra_defs = HITTER_EXTRA_STATS if player_type == "hitter" else PITCHER_EXTRA_STATS
    percentile_rows = league_data["percentile_batters"] if player_type == "hitter" else league_data["percentile_pitchers"]

    pid = str(player_id)
    row = next((r for r in percentile_rows if r.get("player_id") == pid), None)
    if row is None:
        return {}

    return {label: int(row[field]) for field, label in extra_defs if row.get(field) is not None}
