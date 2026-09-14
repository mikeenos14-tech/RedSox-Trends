from __future__ import annotations

from datetime import date, timedelta

import httpx

from . import config

BASE_URL = "https://statsapi.mlb.com/api/v1"

# Standard linear weights (approximate modern-era values). These don't need
# to be exact to the current season to be useful for a form-tracking tool —
# they're stable year to year.
WOBA_WEIGHTS = {"bb": 0.690, "hbp": 0.722, "single": 0.888, "double": 1.271, "triple": 1.616, "hr": 2.101}

# Approximate FIP constant. The precise value requires full-league seasonal
# run environment data; ~3.10 tracks recent MLB seasons closely enough for
# form-tracking purposes.
FIP_CONSTANT = 3.10

LEAGUE_AVG_BABIP = 0.300

# Below these thresholds, a recent-window delta is more noise than signal.
MIN_RECENT_PA = 20
MIN_RECENT_IP = 5.0


def _f(val, default=None) -> float | None:
    """Parse MLB's stat strings (e.g. '.282', '-.--', '.---') to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_innings(ip_str: str | None) -> float:
    """Convert MLB's innings notation ('156.2' = 156 IP + 2 outs) to decimal."""
    if not ip_str:
        return 0.0
    whole, _, partial_outs = str(ip_str).partition(".")
    outs = int(whole or 0) * 3 + int(partial_outs or 0)
    return outs / 3


async def _get_roster(season: int = config.SEASON) -> list[dict]:
    params = {"rosterType": "fullSeason", "season": season}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/teams/{config.TEAM_ID}/roster", params=params)
        resp.raise_for_status()
        return resp.json().get("roster", [])


async def _get_people_with_stats(person_ids: list[int], start: date, end: date, season: int = config.SEASON) -> list[dict]:
    if not person_ids:
        return []

    hydrate = (
        f"stats(group=[hitting,pitching],type=[season,byDateRange],"
        f"startDate={start.isoformat()},endDate={end.isoformat()},season={season})"
    )
    params = {"personIds": ",".join(str(pid) for pid in person_ids), "hydrate": hydrate}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{BASE_URL}/people", params=params)
        resp.raise_for_status()
        return resp.json().get("people", [])


def _first_split(person: dict, stat_type: str, group: str) -> dict | None:
    for stat_block in person.get("stats", []):
        if stat_block["type"]["displayName"] == stat_type and stat_block["group"]["displayName"] == group:
            splits = stat_block.get("splits", [])
            return splits[0]["stat"] if splits else None
    return None


def _hitting_metrics(stat: dict) -> dict:
    ab = stat.get("atBats", 0) or 0
    pa = stat.get("plateAppearances", 0) or 0
    bb = stat.get("baseOnBalls", 0) or 0
    ibb = stat.get("intentionalWalks", 0) or 0
    hbp = stat.get("hitByPitch", 0) or 0
    sf = stat.get("sacFlies", 0) or 0
    h = stat.get("hits", 0) or 0
    doubles = stat.get("doubles", 0) or 0
    triples = stat.get("triples", 0) or 0
    hr = stat.get("homeRuns", 0) or 0
    so = stat.get("strikeOuts", 0) or 0
    singles = h - doubles - triples - hr

    woba_denom = ab + bb - ibb + sf + hbp
    woba = None
    if woba_denom > 0:
        woba_num = (
            WOBA_WEIGHTS["bb"] * (bb - ibb)
            + WOBA_WEIGHTS["hbp"] * hbp
            + WOBA_WEIGHTS["single"] * singles
            + WOBA_WEIGHTS["double"] * doubles
            + WOBA_WEIGHTS["triple"] * triples
            + WOBA_WEIGHTS["hr"] * hr
        )
        woba = round(woba_num / woba_denom, 3)

    avg = _f(stat.get("avg"))
    slg = _f(stat.get("slg"))

    return {
        "games": stat.get("gamesPlayed"),
        "pa": pa,
        "avg": avg,
        "obp": _f(stat.get("obp")),
        "slg": slg,
        "ops": _f(stat.get("ops")),
        "woba": woba,
        "iso": round(slg - avg, 3) if slg is not None and avg is not None else None,
        "babip": _f(stat.get("babip")),
        "bb_pct": round(bb / pa, 3) if pa else None,
        "k_pct": round(so / pa, 3) if pa else None,
        "hr": hr,
    }


def _pitching_metrics(stat: dict) -> dict:
    ip = _parse_innings(stat.get("inningsPitched"))
    hr = stat.get("homeRuns", 0) or 0
    bb = stat.get("baseOnBalls", 0) or 0
    hbp = stat.get("hitByPitch", 0) or 0
    so = stat.get("strikeOuts", 0) or 0
    h = stat.get("hits", 0) or 0
    ab = stat.get("atBats", 0) or 0
    sf = stat.get("sacFlies", 0) or 0
    runs = stat.get("runs", 0) or 0
    batters_faced = stat.get("battersFaced", 0) or 0

    fip = round(((13 * hr) + 3 * (bb + hbp) - (2 * so)) / ip + FIP_CONSTANT, 2) if ip > 0 else None

    babip_denom = ab - so - hr + sf
    babip_against = round((h - hr) / babip_denom, 3) if babip_denom > 0 else None

    lob_denom = h + bb + hbp - 1.4 * hr
    lob_pct = round((h + bb + hbp - runs) / lob_denom, 3) if lob_denom > 0 else None

    return {
        "games": stat.get("gamesPitched"),
        "games_started": stat.get("gamesStarted"),
        "ip": ip,
        "era": _f(stat.get("era")),
        "whip": _f(stat.get("whip")),
        "fip": fip,
        "k_bb_pct": round((so - bb) / batters_faced, 3) if batters_faced else None,
        "babip_against": babip_against,
        "lob_pct": lob_pct,
        "k_per_9": _f(stat.get("strikeoutsPer9Inn")),
        "bb_per_9": _f(stat.get("walksPer9Inn")),
    }


async def get_player_hot_cold_report(hitter_count: int = 9, pitcher_count: int = 8, recent_days: int = 15) -> dict:
    end = date.today()
    start = end - timedelta(days=recent_days)

    roster = await _get_roster()
    person_ids = [entry["person"]["id"] for entry in roster]
    position_by_id = {entry["person"]["id"]: entry.get("position", {}).get("abbreviation") for entry in roster}

    people = await _get_people_with_stats(person_ids, start, end)

    hitter_candidates = []
    pitcher_candidates = []

    for person in people:
        pid = person["id"]
        name = person["fullName"]

        season_hit = _first_split(person, "season", "hitting")
        if season_hit and (season_hit.get("plateAppearances") or 0) > 0:
            recent_hit = _first_split(person, "byDateRange", "hitting")
            season_metrics = _hitting_metrics(season_hit)
            hitter_candidates.append(
                {
                    "name": name,
                    "position": position_by_id.get(pid),
                    "season": season_metrics,
                    "recent": _hitting_metrics(recent_hit) if recent_hit else None,
                    "_pa": season_metrics["pa"],
                }
            )

        season_pitch = _first_split(person, "season", "pitching")
        if season_pitch and _parse_innings(season_pitch.get("inningsPitched")) > 0:
            recent_pitch = _first_split(person, "byDateRange", "pitching")
            season_metrics = _pitching_metrics(season_pitch)
            games = season_pitch.get("gamesPitched") or 1
            starts = season_pitch.get("gamesStarted") or 0
            pitcher_candidates.append(
                {
                    "name": name,
                    "role": "SP" if starts >= games / 2 else "RP",
                    "season": season_metrics,
                    "recent": _pitching_metrics(recent_pitch) if recent_pitch else None,
                    "_ip": season_metrics["ip"],
                }
            )

    top_hitters = sorted(hitter_candidates, key=lambda h: h["_pa"], reverse=True)[:hitter_count]
    top_pitchers = sorted(pitcher_candidates, key=lambda p: p["_ip"], reverse=True)[:pitcher_count]

    for h in top_hitters:
        del h["_pa"]
        r = h["recent"]
        s = h["season"]
        enough_sample = bool(r and (r["pa"] or 0) >= MIN_RECENT_PA)
        h["small_sample"] = bool(r) and not enough_sample
        h["form_delta_woba"] = (
            round(r["woba"] - s["woba"], 3)
            if enough_sample and r["woba"] is not None and s["woba"] is not None
            else None
        )

    for p in top_pitchers:
        del p["_ip"]
        r = p["recent"]
        s = p["season"]
        enough_sample = bool(r and (r["ip"] or 0) >= MIN_RECENT_IP)
        p["small_sample"] = bool(r) and not enough_sample
        p["form_delta_era"] = (
            round(s["era"] - r["era"], 2)
            if enough_sample and r["era"] is not None and s["era"] is not None
            else None
        )

    top_hitters.sort(key=lambda h: h["form_delta_woba"] if h["form_delta_woba"] is not None else -99, reverse=True)
    top_pitchers.sort(key=lambda p: p["form_delta_era"] if p["form_delta_era"] is not None else -99, reverse=True)

    return {
        "league_avg_babip": LEAGUE_AVG_BABIP,
        "window_days": recent_days,
        "hitters": top_hitters,
        "pitchers": top_pitchers,
    }
