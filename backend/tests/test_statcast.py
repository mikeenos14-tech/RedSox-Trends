"""Team Statcast profile built from Savant's team leaderboards."""
from __future__ import annotations

from app import statcast


def _rows(values: dict[str, dict]) -> list[dict]:
    return [{"team_id": team, **{k: str(v) for k, v in fields.items()}} for team, fields in values.items()]


LEAGUE = {
    "team_expected_hitting": _rows({
        "BOS": {"woba": 0.316, "est_woba": 0.309},
        "NYY": {"woba": 0.330, "est_woba": 0.335},
        "TB": {"woba": 0.300, "est_woba": 0.305},
    }),
    "team_contact_hitting": _rows({
        "BOS": {"brl_percent": 7.3, "ev95percent": 35.7, "avg_hit_speed": 87.6, "anglesweetspotpercent": 32.9},
        "NYY": {"brl_percent": 9.0, "ev95percent": 41.0, "avg_hit_speed": 89.9, "anglesweetspotpercent": 34.0},
        "TB": {"brl_percent": 7.3, "ev95percent": 34.6, "avg_hit_speed": 88.0, "anglesweetspotpercent": 29.8},
    }),
    "team_expected_pitching": _rows({
        "BOS": {"woba": 0.302, "est_woba": 0.301},
        "NYY": {"woba": 0.290, "est_woba": 0.295},
        "TB": {"woba": 0.320, "est_woba": 0.310},
    }),
    "team_contact_pitching": _rows({
        "BOS": {"brl_percent": 6.9, "ev95percent": 36.6, "avg_hit_speed": 88.3, "anglesweetspotpercent": 32.6},
        "NYY": {"brl_percent": 7.5, "ev95percent": 38.0, "avg_hit_speed": 88.9, "anglesweetspotpercent": 33.0},
        "TB": {"brl_percent": 8.0, "ev95percent": 39.0, "avg_hit_speed": 89.0, "anglesweetspotpercent": 34.0},
    }),
}


def test_hitting_ranks_higher_is_better():
    hitting = statcast.build_team_profile(LEAGUE)["hitting"]
    assert hitting["xwoba"]["rank"] == 2 and hitting["xwoba"]["of"] == 3
    assert hitting["xwoba"]["display"] == ".309"
    assert hitting["hard_hit_pct"]["rank"] == 2
    assert hitting["avg_ev"]["rank"] == 3 and hitting["avg_ev"]["display"] == "87.6 mph"


def test_ties_share_a_rank():
    # BOS and TB both at 7.3% barrels, NYY above: both are 2nd, nobody is 3rd.
    assert statcast.build_team_profile(LEAGUE)["hitting"]["barrel_pct"]["rank"] == 2


def test_pitching_ranks_lower_is_better_and_labels_allowed():
    pitching = statcast.build_team_profile(LEAGUE)["pitching"]
    assert pitching["hard_hit_pct"]["rank"] == 1
    assert pitching["hard_hit_pct"]["label"] == "Hard-Hit% Allowed"
    assert pitching["xwoba"]["rank"] == 2  # NYY .295 better, TB .310 worse


def test_luck_is_actual_minus_expected():
    profile = statcast.build_team_profile(LEAGUE)
    # The offense the AI once called "unlucky" was outperforming its xwOBA.
    assert profile["hitting_luck"] == {"woba": 0.316, "xwoba": 0.309, "diff": 0.007}
    assert profile["pitching_luck"]["diff"] == 0.001


def test_missing_team_data_degrades_to_empty_profile():
    profile = statcast.build_team_profile({})
    assert profile["hitting"] == {} and profile["pitching"] == {}
    assert profile["hitting_luck"] is None
