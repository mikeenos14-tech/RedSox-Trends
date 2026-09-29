"""Baseball rules and stat math: bullpen availability, hitting streaks, What
Stood Out checks, and the rate-stat formulas."""
from __future__ import annotations

import pytest

from app import bullpen, player_stats, significance

# --- bullpen availability ----------------------------------------------------------


def outing(pitches: int) -> dict:
    return {"pitches": pitches, "innings_pitched": "1.0"}


@pytest.mark.parametrize(
    "outings_by_days_ago, expected",
    [
        ({}, "Available"),
        ({0: outing(12)}, "Used today"),
        # The bug that shipped: 98 pitches yesterday read as "Likely available".
        ({1: outing(98)}, "Likely unavailable"),
        ({1: outing(30)}, "Likely unavailable"),
        ({1: outing(29)}, "Limited"),
        ({1: outing(10), 2: outing(10)}, "Likely unavailable"),  # back-to-back
        ({1: outing(8), 3: outing(8), 2: outing(8)}, "Likely unavailable"),
        ({2: outing(8), 3: outing(8)}, "Available"),  # 2 in 4, none yesterday
        ({1: outing(5), 3: outing(5)}, "Limited"),
        ({2: outing(45)}, "Available"),
    ],
)
def test_bullpen_availability(outings_by_days_ago, expected):
    assert bullpen.availability(outings_by_days_ago) == expected


# --- hitting streaks (scoring rule 9.23(b)) --------------------------------------------

HIT = {"hits": 1, "atBats": 4, "plateAppearances": 4}
HITLESS = {"hits": 0, "atBats": 4, "plateAppearances": 4}
WALKS_ONLY = {"hits": 0, "atBats": 0, "baseOnBalls": 2, "plateAppearances": 2}
SAC_FLY_ONLY = {"hits": 0, "atBats": 0, "sacFlies": 1, "plateAppearances": 1}


@pytest.mark.parametrize(
    "stat, expected",
    [(HIT, True), (HITLESS, False), (WALKS_ONLY, None), (SAC_FLY_ONLY, False)],
)
def test_hit_streak_game_result(stat, expected):
    assert significance._hit_streak_result(stat) is expected


def game_log(stats: list[dict], start_pk: int = 1000) -> list[dict]:
    return [
        {"date": f"2026-08-{i + 1:02d}", "game": {"gamePk": start_pk + i, "gameNumber": 1}, "stat": stat}
        for i, stat in enumerate(stats)
    ]


def last_pk(log):
    return log[-1]["game"]["gamePk"]


def test_ten_game_streak_is_called_out():
    log = game_log([HITLESS] + [HIT] * 10)
    finding = significance.check_hitting_streak(log, "Trevor Story", last_pk(log))
    assert finding["detail"] == "Trevor Story has hit safely in 10 straight games."


def test_five_game_streak_is_not_notable_anymore():
    log = game_log([HITLESS] + [HIT] * 5)
    assert significance.check_hitting_streak(log, "Anyone", last_pk(log)) is None


def test_eleven_game_streak_ending_is_called_out():
    log = game_log([HITLESS] + [HIT] * 11 + [HITLESS])
    finding = significance.check_hitting_streak(log, "Trevor Story", last_pk(log))
    assert finding["detail"] == "Trevor Story's 11-game hitting streak has come to an end."


def test_walks_only_game_pauses_a_streak_instead_of_ending_it():
    log = game_log([HITLESS] + [HIT] * 11 + [WALKS_ONLY])
    assert significance.check_hitting_streak(log, "Anyone", last_pk(log)) is None
    # ...and the streak carries through it: the next hit makes it 12, not 1.
    log = game_log([HITLESS] + [HIT] * 9 + [WALKS_ONLY] + [HIT])
    finding = significance.check_hitting_streak(log, "Anyone", last_pk(log))
    assert finding["value"] == 10


def test_sac_fly_only_game_does_end_a_streak():
    log = game_log([HITLESS] + [HIT] * 10 + [SAC_FLY_ONLY])
    finding = significance.check_hitting_streak(log, "Anyone", last_pk(log))
    assert finding["type"] == "hitting_streak_snapped"


def test_log_that_has_not_caught_up_raises_instead_of_reporting_nothing():
    log = game_log([HIT] * 10)
    with pytest.raises(significance.LogNotCaughtUp):
        significance.check_hitting_streak(log, "Anyone", game_pk=999999)


def test_doubleheader_game_two_is_not_confused_with_game_one():
    # Log has caught up through Game 1 only — same date as Game 2.
    log = game_log([HIT] * 3)
    log[-1]["game"].update(gamePk=5001, gameNumber=1)
    with pytest.raises(significance.LogNotCaughtUp):
        significance.check_multi_hit_or_hr(log, "Anyone", game_pk=5002)


def test_team_streak_keeps_five_game_floor():
    games = [{"date": f"2026-08-{i + 1:02d}", "won": w} for i, w in enumerate([False] + [True] * 5)]
    import asyncio

    finding = asyncio.run(significance.check_team_streak(games))
    assert finding["detail"] == "The Red Sox have a 5-game winning streak."


def test_strikeout_tie_is_matched_not_a_season_high():
    log = game_log([{"strikeOuts": 11, "inningsPitched": "7.0"}, {"strikeOuts": 11, "inningsPitched": "6.0"}])
    finding = significance.check_pitching_outing(log, "Brayan Bello", last_pk(log))
    assert finding["detail"] == "Brayan Bello struck out 11 — matching his season high."


def test_strikeout_season_high():
    log = game_log([{"strikeOuts": 9, "inningsPitched": "7.0"}, {"strikeOuts": 11, "inningsPitched": "6.0"}])
    finding = significance.check_pitching_outing(log, "Brayan Bello", last_pk(log))
    assert finding["detail"] == "Brayan Bello struck out 11 — a season high."


# --- stat math ------------------------------------------------------------------------


@pytest.mark.parametrize("ip, outs", [("156.2", 470), ("0.1", 1), ("5.0", 15), (None, 0), ("", 0)])
def test_innings_notation(ip, outs):
    assert round(player_stats._parse_innings(ip) * 3) == outs


def test_innings_round_trip():
    assert player_stats._format_innings(player_stats._parse_innings("14.1")) == "14.1"


def test_hitting_metrics_rates():
    # 10 PA: 2 singles, 1 double, 1 HR, 2 BB, 4 outs (2 K)
    stat = {
        "atBats": 8, "plateAppearances": 10, "baseOnBalls": 2, "hits": 4, "doubles": 1,
        "homeRuns": 1, "strikeOuts": 2, "avg": ".500", "slg": "1.000",
    }
    m = player_stats._hitting_metrics(stat)
    w = player_stats.WOBA_WEIGHTS
    expected_woba = (2 * w["bb"] + 2 * w["single"] + w["double"] + w["hr"]) / 10
    assert m["woba"] == round(expected_woba, 3)
    assert m["bb_pct"] == 0.2 and m["k_pct"] == 0.2
    assert m["iso"] == 0.5


def test_ai_player_notes_get_percentages_not_fractions():
    line_h = {"woba": 0.3, "babip": 0.3, "bb_pct": 0.11, "k_pct": 0.252, "iso": 0.2, "pa": 60}
    line_p = {"era": 1.0, "fip": 2.0, "k_bb_pct": 0.302, "babip_against": 0.3, "lob_pct": 0.968, "ip_display": "14.1"}
    report = {
        "league_avg_babip": 0.3,
        "window_games": 15,
        "windows": {"hitters": "last 15 games", "starters": "last 5 starts", "relievers": "last 10 appearances"},
        "hitters": [{"name": "H", "position": "RF", "form_delta_woba": 0.01, "small_sample": False, "season": line_h, "recent": line_h}],
        "pitchers": [{"name": "P", "role": "RP", "window": "last 10 appearances", "form_delta_fip": 0.5,
                      "form_delta_era": 1.0, "small_sample": False, "season": line_p, "recent": line_p}],
    }
    slim = player_stats.slim_for_ai(report)
    assert slim["hitters"][0]["recent"]["bb_pct"] == 11.0
    assert slim["hitters"][0]["recent"]["k_pct"] == 25.2
    assert slim["pitchers"][0]["recent"]["k_bb_pct"] == 30.2
    assert slim["pitchers"][0]["recent"]["lob_pct"] == 96.8
    assert slim["hitters"][0]["recent"]["pa"] == 60


def test_traded_player_gets_only_this_teams_line():
    # Real shape for Devers' 2025: combined total first, then one split per team.
    person = {"stats": [{"type": {"displayName": "season"}, "group": {"displayName": "hitting"}, "splits": [
        {"numTeams": 2, "stat": {"plateAppearances": 729}},
        {"team": {"id": 111}, "stat": {"plateAppearances": 334}},
        {"team": {"id": 137}, "stat": {"plateAppearances": 395}},
    ]}]}
    assert player_stats._team_split(person, "season", "hitting", 111)["plateAppearances"] == 334
    assert player_stats._team_split(person, "season", "hitting", 137)["plateAppearances"] == 395
    assert player_stats._team_split(person, "season", "hitting", 147) is None
    assert player_stats._first_split(person, "season", "hitting")["plateAppearances"] == 729  # the old, wrong input
