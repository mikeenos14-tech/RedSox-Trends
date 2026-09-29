"""What Stood Out for playoff games: career-postseason firsts, milestones,
big games, and series outcomes."""
from __future__ import annotations

import pytest

from app import significance

from .conftest import load_fixture

BOS = 111


def plog(*stats: dict, start_pk: int = 9000) -> list[dict]:
    return [{"date": f"2026-10-{i + 1:02d}", "game": {"gamePk": start_pk + i}, "stat": s} for i, s in enumerate(stats)]


def details(findings):
    return [f["detail"] for f in findings]


def test_first_career_postseason_homer():
    log = plog({"homeRuns": 0, "hits": 1}, {"homeRuns": 1, "hits": 1})
    out = significance.check_postseason_hitting(log, {"homeRuns": 1, "hits": 2}, "Trevor Story", 9001)
    assert details(out) == ["Trevor Story hit his first career postseason home run."]


def test_homer_is_not_first_when_he_has_one_from_another_october():
    log = plog({"homeRuns": 1, "hits": 1})
    assert significance.check_postseason_hitting(log, {"homeRuns": 2, "hits": 12}, "Trevor Story", 9000) == []


def test_two_homers_including_his_first_is_one_callout():
    log = plog({"homeRuns": 2, "hits": 2})
    out = significance.check_postseason_hitting(log, {"homeRuns": 2, "hits": 2}, "Roman Anthony", 9000)
    assert details(out) == ["Roman Anthony homered twice — the first postseason home runs of his career."]


def test_replaying_an_earlier_game_subtracts_later_games():
    # Career total now includes a homer from a *later* game this October; the
    # earlier game's homer was still his first.
    log = plog({"homeRuns": 1, "hits": 1}, {"homeRuns": 1, "hits": 1})
    out = significance.check_postseason_hitting(log, {"homeRuns": 2, "hits": 2}, "X", 9000)
    assert details(out) == ["X hit his first career postseason home run."]


def test_lagging_career_totals_mark_the_result_incomplete():
    log = plog({"homeRuns": 1, "hits": 1})
    with pytest.raises(significance.LogNotCaughtUp):
        significance.check_postseason_hitting(log, {"homeRuns": 0, "hits": 0}, "X", 9000)


def test_postseason_milestone():
    log = plog({"homeRuns": 0, "hits": 2})
    out = significance.check_postseason_hitting(log, {"homeRuns": 3, "hits": 25}, "X", 9000)
    assert details(out) == ["X reached 25 career postseason hits."]


def test_crochet_game_one_2025():
    # Real line: 7.2 IP, 11 K, the W — and his first postseason win.
    log = plog({"strikeOuts": 11, "inningsPitched": "7.2", "gamesStarted": 1, "wins": 1, "earnedRuns": 1, "runs": 1})
    career = {"strikeOuts": 17, "wins": 1, "saves": 0}
    out = significance.check_postseason_pitching(log, career, "Garrett Crochet", 9000)
    assert details(out) == [
        "Garrett Crochet struck out 11 in a postseason start.",
        "Garrett Crochet earned his first career postseason win.",
    ]


def test_quiet_game_finds_nothing():
    log = plog({"strikeOuts": 3, "inningsPitched": "5.0", "gamesStarted": 1, "earnedRuns": 2, "runs": 2})
    assert significance.check_postseason_pitching(log, {"strikeOuts": 40, "wins": 3}, "X", 9000) == []


def _real_2025_games():
    data = load_fixture("postseason_2025.json")
    return [g for d in data["dates"] for g in d["games"]]


@pytest.mark.parametrize(
    "game_index, expected",
    [
        (0, None),  # Game 1: 1-0 lead is not a series outcome
        (1, "The Red Sox forced a decisive Game 3 (Series tied 1-1)."),
        (2, "The Red Sox were eliminated from the AL Wild Card Series (NYY wins 2-1)."),
    ],
)
def test_series_outcomes_from_real_2025_series(game_index, expected):
    finding = significance.check_series_outcome(_real_2025_games()[game_index], BOS)
    assert (finding or {}).get("detail") == expected


def test_series_clinch():
    game = _real_2025_games()[2]
    game["seriesStatus"]["winningTeam"] = {"id": BOS}
    game["seriesStatus"]["result"] = "BOS wins 2-1"
    assert significance.check_series_outcome(game, BOS)["detail"] == "The Red Sox won the AL Wild Card Series (BOS wins 2-1)."
