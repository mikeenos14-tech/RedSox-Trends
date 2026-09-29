"""League- and park-adjusted rate stats: OPS+, ERA-, FIP- (100 = league
average), and the season's real FIP constant.

Everything shown elsewhere on the site is raw, which flatters Boston's
hitters and understates its pitchers: Fenway is one of the most
run-friendly parks in baseball. These indexes put a player (or team) on a
league-average scale with that park effect removed.

Formulas are the standard published ones:
- OPS+ (Baseball-Reference): 100 * (OBP / (lgOBP * PF) + SLG / (lgSLG * PF) - 1)
- ERA- / FIP- (FanGraphs): 100 * (X + (X - X * PF)) / lgX
- FIP constant: lgERA - (13*HR + 3*(BB+HBP) - 2*K) / IP, over league totals

PF is a *half-home* park factor: a player plays half his games at home, so
a park that inflates runs 6% moves his season line about 3%. Park indexes
come from Baseball Savant's 3-year rolling Statcast park factors; a park
without one (e.g. a team in a temporary home) is treated as neutral.

wRC+ is deliberately not attempted: it needs a wOBA scale and league run
environment that the site's fixed wOBA weights can't recover exactly, and a
correct OPS+ beats an approximate wRC+.
"""
from __future__ import annotations


def _ip(ip_str) -> float:
    whole, _, outs = str(ip_str or "0").partition(".")
    return int(whole or 0) + int(outs or 0) / 3


def league_baselines(all_team_stats: dict) -> dict | None:
    """League OBP/SLG/ERA and the FIP constant, from summed team totals (not
    an average of team rates, which would weight a small-sample club the
    same as everyone else)."""
    hit = {k: 0 for k in ("h", "bb", "hbp", "sf", "ab", "tb")}
    for split in all_team_stats.get("hitting", []):
        s = split["stat"]
        hit["h"] += s.get("hits", 0) or 0
        hit["bb"] += s.get("baseOnBalls", 0) or 0
        hit["hbp"] += s.get("hitByPitch", 0) or 0
        hit["sf"] += s.get("sacFlies", 0) or 0
        hit["ab"] += s.get("atBats", 0) or 0
        hit["tb"] += s.get("totalBases", 0) or 0
    pit = {k: 0.0 for k in ("er", "ip", "hr", "bb", "hbp", "so")}
    for split in all_team_stats.get("pitching", []):
        s = split["stat"]
        pit["er"] += s.get("earnedRuns", 0) or 0
        pit["ip"] += _ip(s.get("inningsPitched"))
        pit["hr"] += s.get("homeRuns", 0) or 0
        pit["bb"] += s.get("baseOnBalls", 0) or 0
        pit["hbp"] += s.get("hitByPitch", 0) or 0
        pit["so"] += s.get("strikeOuts", 0) or 0

    obp_denom = hit["ab"] + hit["bb"] + hit["hbp"] + hit["sf"]
    if not obp_denom or not hit["ab"] or not pit["ip"]:
        return None
    era = 9 * pit["er"] / pit["ip"]
    return {
        "obp": (hit["h"] + hit["bb"] + hit["hbp"]) / obp_denom,
        "slg": hit["tb"] / hit["ab"],
        "era": era,
        "fip_constant": era - (13 * pit["hr"] + 3 * (pit["bb"] + pit["hbp"]) - 2 * pit["so"]) / pit["ip"],
    }


def half_park_factor(team_id: int | None, park_factors: dict[int, int] | None) -> float:
    index = (park_factors or {}).get(team_id)
    return (1 + index / 100) / 2 if index else 1.0


def ops_plus(obp, slg, lg: dict, pf: float) -> int | None:
    if obp is None or slg is None:
        return None
    return round(100 * (float(obp) / (lg["obp"] * pf) + float(slg) / (lg["slg"] * pf) - 1))


def _minus(value, lg_value: float, pf: float) -> int | None:
    if value is None or not lg_value:
        return None
    v = float(value)
    return round(100 * (v + (v - v * pf)) / lg_value)


def era_minus(era, lg: dict, pf: float) -> int | None:
    return _minus(era, lg["era"], pf)


def fip_minus(fip, lg: dict, pf: float) -> int | None:
    # League FIP equals league ERA by construction of the FIP constant.
    return _minus(fip, lg["era"], pf)
