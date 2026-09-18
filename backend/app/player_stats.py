from __future__ import annotations

import asyncio
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

# A player whose last qualifying game is older than this isn't "recently
# hot or cold" in any meaningful sense, regardless of what their last 15
# games (whenever they were) looked like.
STALE_AFTER_DAYS = 12


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


async def get_roster(season: int = config.SEASON, roster_type: str = "40Man") -> list[dict]:
    # 40Man, not fullSeason — fullSeason includes anyone who passed through
    # the org this year (trades, DFAs, releases included), which surfaces
    # players no longer with the team. 40Man reflects who's actually still
    # rostered right now. Callers that specifically care about who's
    # currently playable (not injured, not optioned down) should pass
    # roster_type="active" instead — the 40-man roster includes IL players,
    # which is exactly wrong for a "recent form" report.
    params = {"rosterType": roster_type, "season": season}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/teams/{config.TEAM_ID}/roster", params=params)
        resp.raise_for_status()
        return resp.json().get("roster", [])


async def _get_people_with_stats(person_ids: list[int], season: int = config.SEASON) -> list[dict]:
    if not person_ids:
        return []

    hydrate = f"stats(group=[hitting,pitching],type=[season],season={season})"
    params = {"personIds": ",".join(str(pid) for pid in person_ids), "hydrate": hydrate}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{BASE_URL}/people", params=params)
        resp.raise_for_status()
        return resp.json().get("people", [])


async def _get_game_log(client: httpx.AsyncClient, person_id: int, season: int, group: str) -> list[dict]:
    resp = await client.get(
        f"{BASE_URL}/people/{person_id}/stats", params={"stats": "gameLog", "group": group, "season": season}
    )
    resp.raise_for_status()
    stats = resp.json().get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    return sorted(splits, key=lambda g: g["date"])


def _format_innings(decimal_ip: float) -> str:
    outs = round(decimal_ip * 3)
    whole, part = divmod(outs, 3)
    return f"{whole}.{part}"


def _sum_hitting_games(games: list[dict]) -> dict:
    """Aggregate raw counting stats across a set of individual game-log
    entries into the same shape MLB's own 'season'/'byDateRange' stat
    blocks use, so it can flow through _hitting_metrics() unchanged."""
    fields = [
        "atBats", "plateAppearances", "baseOnBalls", "intentionalWalks", "hitByPitch", "sacFlies",
        "hits", "doubles", "triples", "homeRuns", "strikeOuts", "rbi",
    ]
    totals = {f: sum((g["stat"].get(f) or 0) for g in games) for f in fields}
    totals["gamesPlayed"] = len(games)

    ab = totals["atBats"]
    h = totals["hits"]
    hr = totals["homeRuns"]
    doubles = totals["doubles"]
    triples = totals["triples"]
    singles = h - doubles - triples - hr
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hr

    avg = h / ab if ab else None
    obp_denom = ab + totals["baseOnBalls"] + totals["hitByPitch"] + totals["sacFlies"]
    obp = (h + totals["baseOnBalls"] + totals["hitByPitch"]) / obp_denom if obp_denom else None
    slg = total_bases / ab if ab else None
    babip_denom = ab - totals["strikeOuts"] - hr + totals["sacFlies"]

    totals["avg"] = round(avg, 3) if avg is not None else None
    totals["obp"] = round(obp, 3) if obp is not None else None
    totals["slg"] = round(slg, 3) if slg is not None else None
    totals["ops"] = round(obp + slg, 3) if obp is not None and slg is not None else None
    totals["babip"] = round((h - hr) / babip_denom, 3) if babip_denom > 0 else None
    return totals


def _sum_pitching_games(games: list[dict]) -> dict:
    fields = ["homeRuns", "baseOnBalls", "hitByPitch", "strikeOuts", "hits", "atBats", "sacFlies", "runs", "earnedRuns", "battersFaced"]
    totals = {f: sum((g["stat"].get(f) or 0) for g in games) for f in fields}
    ip = sum(_parse_innings(g["stat"].get("inningsPitched")) for g in games)
    totals["inningsPitched"] = _format_innings(ip)
    totals["gamesPitched"] = len(games)
    totals["gamesStarted"] = sum(1 for g in games if (g["stat"].get("gamesStarted") or 0) > 0)

    totals["era"] = round(totals["earnedRuns"] * 9 / ip, 2) if ip > 0 else None
    totals["whip"] = round((totals["baseOnBalls"] + totals["hits"]) / ip, 2) if ip > 0 else None
    totals["strikeoutsPer9Inn"] = round(totals["strikeOuts"] * 9 / ip, 1) if ip > 0 else None
    totals["walksPer9Inn"] = round(totals["baseOnBalls"] * 9 / ip, 1) if ip > 0 else None
    return totals


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
        "rbi": stat.get("rbi"),
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


RECENT_GAMES_WINDOW = 15


async def get_player_hot_cold_report(recent_games: int = RECENT_GAMES_WINDOW) -> dict:
    """Every roster player with at least one plate appearance or inning
    pitched among their own last `recent_games` games actually played — a
    rolling per-player window of real appearances, not a shared calendar
    window. A calendar window (e.g. "last 15 days") understates a player's
    recent form the moment they missed time inside it (a day off, a short
    IL stint) — two players who both "played in the last 15 days" can have
    wildly different real sample sizes. Keying off each player's own last N
    games played keeps the sample consistent, and still surfaces a mid-season
    callup or a low-innings reliever the moment they have enough of a log to
    judge, instead of being crowded out by season-long counting stats.
    """
    # "active", not the default 40-man — the 40-man roster keeps injured
    # players on it for the length of their IL stint, which is exactly wrong
    # here: an IL player's last real game could be from months ago, and
    # comparing that stale stretch to their season line produces a
    # confidently wrong "hot" or "cold" read for someone who hasn't
    # actually played recently at all.
    roster = await get_roster(roster_type="active")
    person_ids = [entry["person"]["id"] for entry in roster]
    position_by_id = {entry["person"]["id"]: entry.get("position", {}).get("abbreviation") for entry in roster}
    season = config.SEASON
    # Belt-and-suspenders on top of the active-roster filter: skip anyone
    # whose last qualifying game is older than this, in case the active-
    # roster snapshot hasn't caught up with a very recent IL move yet.
    stale_cutoff = date.today() - timedelta(days=STALE_AFTER_DAYS)

    people = await _get_people_with_stats(person_ids, season)

    async with httpx.AsyncClient(timeout=20) as client:
        hitting_logs = await asyncio.gather(
            *(_get_game_log(client, pid, season, "hitting") for pid in person_ids), return_exceptions=True
        )
        pitching_logs = await asyncio.gather(
            *(_get_game_log(client, pid, season, "pitching") for pid in person_ids), return_exceptions=True
        )
    hitting_log_by_id = {pid: log for pid, log in zip(person_ids, hitting_logs) if not isinstance(log, Exception)}
    pitching_log_by_id = {pid: log for pid, log in zip(person_ids, pitching_logs) if not isinstance(log, Exception)}

    hitters = []
    pitchers = []

    for person in people:
        pid = person["id"]
        name = person["fullName"]

        hitting_log = hitting_log_by_id.get(pid, [])
        recent_hit_games = [g for g in hitting_log if (g["stat"].get("plateAppearances") or 0) > 0][-recent_games:]
        if recent_hit_games and date.fromisoformat(recent_hit_games[-1]["date"]) >= stale_cutoff:
            season_hit = _first_split(person, "season", "hitting")
            recent_metrics = _hitting_metrics(_sum_hitting_games(recent_hit_games))
            season_metrics = _hitting_metrics(season_hit) if season_hit else None
            enough_sample = (recent_metrics["pa"] or 0) >= MIN_RECENT_PA
            hitters.append(
                {
                    "name": name,
                    "position": position_by_id.get(pid),
                    "season": season_metrics,
                    "recent": recent_metrics,
                    "small_sample": not enough_sample,
                    "form_delta_woba": (
                        round(recent_metrics["woba"] - season_metrics["woba"], 3)
                        if enough_sample
                        and season_metrics
                        and recent_metrics["woba"] is not None
                        and season_metrics["woba"] is not None
                        else None
                    ),
                }
            )

        pitching_log = pitching_log_by_id.get(pid, [])
        recent_pitch_games = [
            g for g in pitching_log if _parse_innings(g["stat"].get("inningsPitched")) > 0
        ][-recent_games:]
        if recent_pitch_games and date.fromisoformat(recent_pitch_games[-1]["date"]) >= stale_cutoff:
            season_pitch = _first_split(person, "season", "pitching")
            recent_metrics = _pitching_metrics(_sum_pitching_games(recent_pitch_games))
            season_metrics = _pitching_metrics(season_pitch) if season_pitch else None
            enough_sample = (recent_metrics["ip"] or 0) >= MIN_RECENT_IP
            games = (season_pitch or {}).get("gamesPitched") or len(recent_pitch_games)
            starts = (season_pitch or {}).get("gamesStarted") or 0
            pitchers.append(
                {
                    "name": name,
                    "role": "SP" if starts >= games / 2 else "RP",
                    "season": season_metrics,
                    "recent": recent_metrics,
                    "small_sample": not enough_sample,
                    "form_delta_era": (
                        round(season_metrics["era"] - recent_metrics["era"], 2)
                        if enough_sample
                        and season_metrics
                        and recent_metrics["era"] is not None
                        and season_metrics["era"] is not None
                        else None
                    ),
                }
            )

    hitters.sort(key=lambda h: h["form_delta_woba"] if h["form_delta_woba"] is not None else -99, reverse=True)
    pitchers.sort(key=lambda p: p["form_delta_era"] if p["form_delta_era"] is not None else -99, reverse=True)

    return {
        "league_avg_babip": LEAGUE_AVG_BABIP,
        "window_games": recent_games,
        "hitters": hitters,
        "pitchers": pitchers,
    }


def slim_for_ai(report: dict) -> dict:
    """Trim the report to just what the player-notes prompt needs: players
    with a large enough recent sample to say anything meaningful about, and
    only the specific fields that feed the verdict. Keeps the roster grown
    from get_player_hot_cold_report() from ballooning the prompt/thinking
    budget now that it covers the whole active roster (~35-40 players)
    instead of a fixed top-N.
    """

    def slim_hitter(h: dict) -> dict:
        s, r = h["season"], h["recent"]
        return {
            "name": h["name"],
            "position": h["position"],
            "form_delta_woba": h["form_delta_woba"],
            "season": s and {"woba": s["woba"], "babip": s["babip"], "bb_pct": s["bb_pct"], "k_pct": s["k_pct"], "iso": s["iso"]},
            "recent": {"woba": r["woba"], "babip": r["babip"], "bb_pct": r["bb_pct"], "k_pct": r["k_pct"], "iso": r["iso"]},
        }

    def slim_pitcher(p: dict) -> dict:
        s, r = p["season"], p["recent"]
        return {
            "name": p["name"],
            "role": p["role"],
            "form_delta_era": p["form_delta_era"],
            "season": s and {"era": s["era"], "fip": s["fip"], "k_bb_pct": s["k_bb_pct"], "babip_against": s["babip_against"], "lob_pct": s["lob_pct"]},
            "recent": {"era": r["era"], "fip": r["fip"], "k_bb_pct": r["k_bb_pct"], "babip_against": r["babip_against"], "lob_pct": r["lob_pct"]},
        }

    return {
        "league_avg_babip": report["league_avg_babip"],
        "window_games": report["window_games"],
        "hitters": [slim_hitter(h) for h in report["hitters"] if not h["small_sample"]],
        "pitchers": [slim_pitcher(p) for p in report["pitchers"] if not p["small_sample"]],
    }
