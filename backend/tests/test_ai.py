"""The AI pipeline's deterministic parts: the recap fact sheet, the output
backstop, and the persistent store. Claude itself is replaced by a stub —
these tests cost nothing and never hit the API."""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app import ai_recap, ai_store, game_recap

from .conftest import load_fixture


@pytest.fixture
def recap_game():
    return load_fixture("recap_824705.json")


class StubClaude:
    """Stands in for ai_recap._create_message: returns queued texts in order
    and counts calls."""

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        text = self.texts[min(self.calls, len(self.texts)) - 1]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")


@pytest.fixture
def stub_claude(monkeypatch, temp_ai_store):
    def install(*texts):
        stub = StubClaude(*texts)
        monkeypatch.setattr(ai_recap, "_create_message", stub)
        return stub

    return install


# --- recap fact sheet (real 9/27/2026 CHC @ BOS game) --------------------------------


def test_fact_sheet_marks_lead_changes_and_ties(recap_game):
    sheet = ai_recap.build_recap_fact_sheet(recap_game)
    assert "FINAL: Red Sox 2, Chicago Cubs 6 (Red Sox loss" in sheet
    assert sheet.count("-> This play TIED the game.") == 1
    assert sheet.count("-> Chicago Cubs took the lead here.") == 1
    assert sheet.count("-> Chicago Cubs retook the lead here.") == 1


def test_direct_lead_flip_is_not_called_retaking():
    def play(inning, half, batting, us, them):
        return {"inning": inning, "half": half, "team_batting": batting, "pitcher_on_mound": "P",
                "description": "x.", "runs_on_play": 1, "score_after": {"us": us, "them": them}}

    game = {
        "opponent": "New York Yankees", "our_score": 3, "their_score": 2, "won": True, "home_or_away": "home",
        "pitching": {}, "top_performers": {},
        # NYY 2-0, BOS 2-1, BOS 3-2 (straight from trailing to leading): Boston never led before.
        "scoring_plays": [play(1, "top", "them", 0, 2), play(4, "bottom", "us", 1, 2), play(6, "bottom", "us", 3, 2)],
    }
    sheet = ai_recap.build_recap_fact_sheet(game)
    assert "-> Red Sox took the lead here." in sheet
    assert "retook" not in sheet and "back" not in sheet


def test_fact_sheet_states_exact_runs_per_play(recap_game):
    sheet = ai_recap.build_recap_fact_sheet(recap_game)
    # Bregman's ninth-inning double scored exactly one run (the model had
    # called it a "two-run double").
    ninth = [line for line in sheet.splitlines() if line.startswith("- Top 9th")]
    assert len(ninth) == 3
    assert all("scored 1 run " in line for line in ninth)
    assert "Top 1st, Chicago Cubs scored 2 runs" in sheet


def test_fact_sheet_spells_out_every_pitchers_runs(recap_game):
    sheet = ai_recap.build_recap_fact_sheet(recap_game)
    garrett = next(line for line in sheet.splitlines() if line.startswith("- Chicago Cubs: Braxton Garrett"))
    # He allowed the tying run in the 2nd — never "scoreless".
    assert "1 R, 1 ER" in garrett and "allowed no runs" not in garrett
    assert "reliever" in garrett and "W, 1-1" in garrett
    assert "Tanner Houck (starter)" in sheet


def test_fact_sheet_uses_full_opponent_name():
    game = {
        "opponent": "Chicago White Sox", "our_score": 1, "their_score": 0, "won": True,
        "home_or_away": "home", "scoring_plays": [], "pitching": {}, "top_performers": {},
    }
    sheet = ai_recap.build_recap_fact_sheet(game)
    assert "Chicago White Sox 0" in sheet and " Sox 0" not in sheet.replace("White Sox 0", "")


# --- output backstop ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, bad",
    [
        ("Bregman added a two-run double in the ninth.", ["two-run double"]),
        ("Bregman opened with a two-run homer.", []),  # real: 2-run HR in the 1st
        ("an RBI double and a 1-run double", []),
        ("It ended on a grand slam.", ["grand slam"]),
        ("A night at Fenway to forget.", ["Fenway"]),  # this game was at Tropicana Field
        ("Conforto's three-run blast", ["three-run blast"]),
    ],
)
def test_backstop_flags_unsupported_claims(recap_game, text, bad):
    assert ai_recap.invalid_run_counts(text, recap_game) == bad


def test_backstop_strip_is_always_true():
    text = "a two-run double and a grand slam"
    assert ai_recap._strip_run_counts(text, ["two-run double", "grand slam"]) == "a double and a home run"


def test_recap_retries_once_then_accepts_clean_output(stub_claude, recap_game):
    stub = stub_claude("A two-run double iced it.", "An RBI double iced it.")
    assert asyncio.run(ai_recap.generate_game_recap(recap_game)) == "An RBI double iced it."
    assert stub.calls == 2


def test_recap_strips_bad_count_if_retry_also_fails(stub_claude, recap_game):
    stub = stub_claude("A two-run double iced it.", "Again, a two-run double iced it.")
    assert asyncio.run(ai_recap.generate_game_recap(recap_game)) == "Again, a double iced it."
    assert stub.calls == 2


def test_clean_recap_is_not_retried(stub_claude, recap_game):
    stub = stub_claude("Bregman's two-run homer set the tone.")
    asyncio.run(ai_recap.generate_game_recap(recap_game))
    assert stub.calls == 1


# --- persistence ----------------------------------------------------------------------


def test_recap_is_keyed_by_game_not_by_drifting_headlines(stub_claude, recap_game):
    stub = stub_claude("First recap.", "Second recap.")
    first = asyncio.run(ai_recap.generate_game_recap(recap_game))
    later = copy.deepcopy(recap_game)
    later["articles"] = [{"title": "A brand-new headline two days later", "source": "X", "link": "y"}]
    assert asyncio.run(ai_recap.generate_game_recap(later)) == first
    assert stub.calls == 1


def test_prompt_edit_regenerates(stub_claude, recap_game, monkeypatch):
    stub = stub_claude("Old prompt recap.", "New prompt recap.")
    asyncio.run(ai_recap.generate_game_recap(recap_game))
    monkeypatch.setattr(ai_recap, "GAME_RECAP_SYSTEM_PROMPT", ai_recap.GAME_RECAP_SYSTEM_PROMPT + " Be brief.")
    assert asyncio.run(ai_recap.generate_game_recap(recap_game)) == "New prompt recap."
    assert stub.calls == 2


def test_analysis_regenerates_only_when_inputs_change(stub_claude):
    stub = stub_claude("Take one.", "Take two.")
    summary = {"record": {"wins": 87, "losses": 75}}
    asyncio.run(ai_recap.generate_team_analysis(summary))
    asyncio.run(ai_recap.generate_team_analysis(dict(summary)))
    assert stub.calls == 1
    assert asyncio.run(ai_recap.generate_team_analysis({"record": {"wins": 88, "losses": 75}})) == "Take two."


def test_store_survives_a_restart(temp_ai_store, monkeypatch):
    ai_store.put("kind", "k", {"text": "hello"})
    ai_store._conn.close()
    monkeypatch.setattr(ai_store, "_conn", None)  # new process, same volume
    assert ai_store.get("kind", "k") == {"text": "hello"}


def test_latest_row_wins_and_history_is_kept(temp_ai_store):
    ai_store.put("kind", "k", "v1")
    ai_store.put("kind", "k", "v2")
    assert ai_store.get("kind", "k") == "v2"
    assert ai_store._conn.execute("SELECT COUNT(*) FROM ai_outputs").fetchone()[0] == 2


def test_broken_store_degrades_to_regenerating(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("AI_CACHE_DB", str(blocker / "ai.sqlite3"))
    monkeypatch.setattr(ai_store, "_conn", None)
    assert ai_store.get("kind", "k") is None
    ai_store.put("kind", "k", "v")  # must not raise


# --- scoring plays -------------------------------------------------------------------


def test_runs_on_play_computed_from_score_deltas(fake_mlb):
    def play(half, inning, away, home, scoring=True, desc="x"):
        return {
            "about": {"halfInning": half, "inning": inning, "isScoringPlay": scoring},
            "result": {"description": desc, "awayScore": away, "homeScore": home},
            "matchup": {"pitcher": {"fullName": "P"}},
        }

    fake_mlb.add(
        "/playByPlay",
        {"allPlays": [play("top", 1, 2, 0), play("bottom", 1, 2, 0, scoring=False), play("bottom", 2, 2, 4), play("top", 9, 3, 4)]},
    )
    plays = asyncio.run(game_recap.get_scoring_plays(1, us_side="home"))
    assert [p["runs_on_play"] for p in plays] == [2, 4, 1]
    assert [p["team_batting"] for p in plays] == ["them", "us", "them"]
    assert plays[-1]["score_after"] == {"us": 4, "them": 3}
