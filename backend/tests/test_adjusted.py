"""League- and park-adjusted stats: OPS+, ERA-, FIP-, and the FIP constant."""
from __future__ import annotations

import pytest

from app import adjusted, league_context, player_stats

LG = {"obp": 0.320, "slg": 0.400, "era": 4.00, "fip_constant": 3.10}


def test_ops_plus_league_average_is_100():
    assert adjusted.ops_plus(".320", ".400", LG, 1.0) == 100


def test_ops_plus_matches_hand_computation():
    # 100 * (.352/.320 + .480/.400 - 1) = 100 * (1.10 + 1.20 - 1) = 130
    assert adjusted.ops_plus(0.352, 0.480, LG, 1.0) == 130


def test_hitter_friendly_park_lowers_ops_plus():
    # Same raw line at Fenway (half-park 1.03) is worth less than neutral.
    assert adjusted.ops_plus(0.352, 0.480, LG, 1.03) < adjusted.ops_plus(0.352, 0.480, LG, 1.0)


def test_era_minus_and_park():
    assert adjusted.era_minus(4.00, LG, 1.0) == 100
    assert adjusted.era_minus(3.00, LG, 1.0) == 75
    # FanGraphs: ERA- = 100 * (ERA + (ERA - ERA*PF)) / lgERA -> 3.00 at PF 1.03 = 72.75
    assert adjusted.era_minus(3.00, LG, 1.03) == 73
    assert adjusted.fip_minus(None, LG, 1.0) is None


def test_half_park_factor():
    parks = {111: 106, 136: 85}
    assert adjusted.half_park_factor(111, parks) == pytest.approx(1.03)
    assert adjusted.half_park_factor(136, parks) == pytest.approx(0.925)
    assert adjusted.half_park_factor(133, parks) == 1.0  # no 3-year sample: neutral


def _team(hit: dict, pit: dict, tid: int = 1):
    return {"team": {"id": tid, "name": f"T{tid}"}, "stat": {**hit, **pit}}


def test_league_baselines_sum_team_totals():
    ats = {
        "hitting": [
            {"team": {"id": 1}, "stat": {"hits": 150, "baseOnBalls": 50, "hitByPitch": 5, "sacFlies": 5, "atBats": 600, "totalBases": 250}},
            {"team": {"id": 2}, "stat": {"hits": 50, "baseOnBalls": 10, "hitByPitch": 0, "sacFlies": 0, "atBats": 200, "totalBases": 70}},
        ],
        "pitching": [
            {"team": {"id": 1}, "stat": {"earnedRuns": 40, "inningsPitched": "90.0", "homeRuns": 10, "baseOnBalls": 30, "hitByPitch": 3, "strikeOuts": 80}},
        ],
    }
    b = adjusted.league_baselines(ats)
    assert b["obp"] == pytest.approx(265 / 870)
    assert b["slg"] == pytest.approx(320 / 800)
    assert b["era"] == pytest.approx(4.0)
    # 4.0 - (130 + 99 - 160) / 90
    assert b["fip_constant"] == pytest.approx(4.0 - 69 / 90)


def test_fip_constant_is_bounded(monkeypatch):
    monkeypatch.setitem(player_stats._fip_constant, "value", 3.10)
    player_stats.set_fip_constant(9.9)  # nonsense from a broken fetch is ignored
    assert player_stats.fip_constant() == 3.10
    player_stats.set_fip_constant(3.094)
    assert player_stats.fip_constant() == 3.094


def test_team_indexes_are_omitted_without_park_factors():
    split = lambda tid, obp, slg, era: None  # noqa: E731
    ats = {
        "hitting": [{"team": {"id": t, "name": str(t)}, "stat": {"hits": 100, "baseOnBalls": 30, "atBats": 400, "totalBases": 160, "obp": ".300", "slg": ".400", "runs": 50, "plateAppearances": 440}} for t in (111, 147)],
        "pitching": [{"team": {"id": t, "name": str(t)}, "stat": {"earnedRuns": 40, "inningsPitched": "90.0", "era": "4.00", "runs": 45, "battersFaced": 380}} for t in (111, 147)],
    }
    without = league_context.compute_league_context(111, ats, None)
    assert without["team_ops_plus"] is None and without["team_era_minus"] is None
    with_parks = league_context.compute_league_context(111, ats, {111: 106, 147: 102})
    assert with_parks["team_ops_plus"]["value"] < 100  # identical lines, but BOS plays in the friendlier park
    assert with_parks["team_ops_plus"]["rank"] == 2
