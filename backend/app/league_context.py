from __future__ import annotations

import httpx

from . import config
from .player_stats import FIP_CONSTANT, WOBA_WEIGHTS, _parse_innings

BASE_URL = "https://statsapi.mlb.com/api/v1"


async def _fetch_league_team_stats(group: str, season: int = config.SEASON) -> list[dict]:
    params = {"stats": "season", "group": group, "season": season, "sportId": 1}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}/teams/stats", params=params)
        resp.raise_for_status()
        data = resp.json()

    splits = []
    for block in data.get("stats", []):
        if block["type"]["displayName"] == "season":
            splits.extend(block.get("splits", []))
    return splits


def _team_woba(stat: dict) -> float | None:
    ab = stat.get("atBats", 0) or 0
    bb = stat.get("baseOnBalls", 0) or 0
    ibb = stat.get("intentionalWalks", 0) or 0
    hbp = stat.get("hitByPitch", 0) or 0
    sf = stat.get("sacFlies", 0) or 0
    h = stat.get("hits", 0) or 0
    doubles = stat.get("doubles", 0) or 0
    triples = stat.get("triples", 0) or 0
    hr = stat.get("homeRuns", 0) or 0
    singles = h - doubles - triples - hr

    denom = ab + bb - ibb + sf + hbp
    if denom <= 0:
        return None

    num = (
        WOBA_WEIGHTS["bb"] * (bb - ibb)
        + WOBA_WEIGHTS["hbp"] * hbp
        + WOBA_WEIGHTS["single"] * singles
        + WOBA_WEIGHTS["double"] * doubles
        + WOBA_WEIGHTS["triple"] * triples
        + WOBA_WEIGHTS["hr"] * hr
    )
    return round(num / denom, 3)


def _team_fip(stat: dict) -> float | None:
    ip = _parse_innings(stat.get("inningsPitched"))
    if ip <= 0:
        return None
    hr = stat.get("homeRuns", 0) or 0
    bb = stat.get("baseOnBalls", 0) or 0
    hbp = stat.get("hitByPitch", 0) or 0
    so = stat.get("strikeOuts", 0) or 0
    return round(((13 * hr) + 3 * (bb + hbp) - (2 * so)) / ip + FIP_CONSTANT, 2)


def _rank_asc(values: dict[int, float], team_id: int) -> tuple[int, int] | None:
    """Rank where LOWER is better (e.g. ERA, runs allowed). Returns (rank, total)."""
    if team_id not in values:
        return None
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    rank = next(i for i, (tid, _) in enumerate(ordered, start=1) if tid == team_id)
    return rank, len(ordered)


def _rank_desc(values: dict[int, float], team_id: int) -> tuple[int, int] | None:
    """Rank where HIGHER is better (e.g. wOBA, runs scored). Returns (rank, total)."""
    if team_id not in values:
        return None
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    rank = next(i for i, (tid, _) in enumerate(ordered, start=1) if tid == team_id)
    return rank, len(ordered)


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


async def get_league_context(team_id: int = config.TEAM_ID) -> dict:
    hitting_splits = await _fetch_league_team_stats("hitting")
    pitching_splits = await _fetch_league_team_stats("pitching")

    runs_scored: dict[int, float] = {}
    runs_allowed: dict[int, float] = {}
    team_woba: dict[int, float] = {}
    team_ops: dict[int, float] = {}
    team_bb_pct: dict[int, float] = {}
    team_k_pct: dict[int, float] = {}
    team_names: dict[int, str] = {}

    for split in hitting_splits:
        tid = split["team"]["id"]
        stat = split["stat"]
        team_names[tid] = split["team"]["name"]
        runs_scored[tid] = stat.get("runs", 0) or 0
        ops = stat.get("ops")
        if ops is not None:
            team_ops[tid] = float(ops)
        woba = _team_woba(stat)
        if woba is not None:
            team_woba[tid] = woba
        pa = stat.get("plateAppearances", 0) or 0
        if pa:
            team_bb_pct[tid] = round((stat.get("baseOnBalls", 0) or 0) / pa, 3)
            team_k_pct[tid] = round((stat.get("strikeOuts", 0) or 0) / pa, 3)

    team_era: dict[int, float] = {}
    team_fip: dict[int, float] = {}
    team_k_bb_pct: dict[int, float] = {}

    for split in pitching_splits:
        tid = split["team"]["id"]
        stat = split["stat"]
        runs_allowed[tid] = stat.get("runs", 0) or 0
        era = stat.get("era")
        if era is not None:
            team_era[tid] = float(era)
        fip = _team_fip(stat)
        if fip is not None:
            team_fip[tid] = fip
        bf = stat.get("battersFaced", 0) or 0
        if bf:
            team_k_bb_pct[tid] = round(
                ((stat.get("strikeOuts", 0) or 0) - (stat.get("baseOnBalls", 0) or 0)) / bf, 3
            )

    run_diff = {tid: runs_scored.get(tid, 0) - runs_allowed.get(tid, 0) for tid in team_names}

    def rank_block(values: dict[int, float], ascending_is_better: bool):
        rank_fn = _rank_asc if ascending_is_better else _rank_desc
        r = rank_fn(values, team_id)
        return {
            "value": values.get(team_id),
            "league_avg": _avg(list(values.values())),
            "rank": r[0] if r else None,
            "of": r[1] if r else None,
        }

    run_diff_league = sorted(
        (
            {"team": team_names[tid], "run_diff": run_diff[tid], "is_boston": tid == team_id}
            for tid in team_names
        ),
        key=lambda d: d["run_diff"],
        reverse=True,
    )

    return {
        "runs_scored": rank_block(runs_scored, ascending_is_better=False),
        "runs_allowed": rank_block(runs_allowed, ascending_is_better=True),
        "run_differential": rank_block(run_diff, ascending_is_better=False),
        "team_woba": rank_block(team_woba, ascending_is_better=False),
        "team_ops": rank_block(team_ops, ascending_is_better=False),
        "team_bb_pct": rank_block(team_bb_pct, ascending_is_better=False),
        "team_k_pct": rank_block(team_k_pct, ascending_is_better=True),
        "team_era": rank_block(team_era, ascending_is_better=True),
        "team_fip": rank_block(team_fip, ascending_is_better=True),
        "team_k_bb_pct": rank_block(team_k_bb_pct, ascending_is_better=False),
        "run_diff_league_chart": run_diff_league,
    }
