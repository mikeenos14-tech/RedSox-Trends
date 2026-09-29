"""Series win probability — a transparent, standard model, not a black box.

1. Team strength: Pythagorean win% from regular-season runs scored and
   allowed (exponent 1.83), regressed toward .500 by 69 games (Tango's
   regression constant for MLB win%): a full season of run differential
   still overstates true talent, and the playoffs compress it further.
2. One game: log5 of the two strengths, then home-field advantage applied
   as an odds multiplier (home teams win ~54% of otherwise even games).
3. Series: exact probability of reaching the needed wins over the
   remaining games in the real home/away order from MLB's schedule,
   starting from the current series score.

Deliberately not modeled: starting pitchers, bullpen usage, injuries, and
roster changes.

NOT SHOWN ON THE SITE, on purpose. Backtested on every 2021-2025
postseason game (208 games; scripts/backtest_odds.py), the model's
favorite won 49.5% and its Brier score (0.251) didn't beat a coin flip
(0.250); heavier regression or a smaller home-field edge didn't change
that. Single playoff games between playoff teams are close to coin flips,
and season-level strength can't separate them. Publishing "Red Sox 40% to
win the series" would claim precision the model doesn't have.

It stays as the base for regular-season playoff odds, where 100+ remaining
games let team strength actually predict — and anything built on it must
beat the coin-flip baseline in scripts/backtest_odds.py before it's shown.
"""
from __future__ import annotations

from functools import lru_cache

PYTHAG_EXPONENT = 1.83
REGRESSION_GAMES = 69
HOME_FIELD = 0.54


def pythagorean(runs_scored: float, runs_allowed: float) -> float:
    rs, ra = runs_scored ** PYTHAG_EXPONENT, runs_allowed ** PYTHAG_EXPONENT
    return rs / (rs + ra)


def true_talent(runs_scored: float, runs_allowed: float, games: int) -> float:
    return (pythagorean(runs_scored, runs_allowed) * games + 0.5 * REGRESSION_GAMES) / (games + REGRESSION_GAMES)


def log5(p_a: float, p_b: float) -> float:
    return p_a * (1 - p_b) / (p_a * (1 - p_b) + p_b * (1 - p_a))


def game_win_probability(p_us: float, p_them: float, us_home: bool) -> float:
    p = log5(p_us, p_them)
    edge = HOME_FIELD / (1 - HOME_FIELD)
    odds = p / (1 - p) * (edge if us_home else 1 / edge)
    return odds / (1 + odds)


def series_win_probability(p_game_by_index: list[float], us_wins: int, them_wins: int, wins_needed: int) -> float:
    """Exact probability over the remaining game sequence (p for each
    remaining game, in order, from our side)."""

    @lru_cache(maxsize=None)
    def win_from(i: int, us: int, them: int) -> float:
        if us >= wins_needed:
            return 1.0
        if them >= wins_needed or i >= len(p_game_by_index):
            return 0.0
        p = p_game_by_index[i]
        return p * win_from(i + 1, us + 1, them) + (1 - p) * win_from(i + 1, us, them + 1)

    return win_from(0, us_wins, them_wins)


def series_odds(postseason: dict | None, remaining_games: list[dict], us_record: dict, them_record: dict) -> dict | None:
    """Odds for the current series, from trends.summarize_postseason output
    and the not-yet-played games of that series (with home_or_away)."""
    if not postseason or postseason["phase"] != "in_series" or not remaining_games:
        return None
    try:
        p_us = true_talent(us_record["runs_scored"], us_record["runs_allowed"], us_record["wins"] + us_record["losses"])
        p_them = true_talent(them_record["runs_scored"], them_record["runs_allowed"], them_record["wins"] + them_record["losses"])
    except (KeyError, TypeError, ZeroDivisionError):
        return None

    games_in_series = remaining_games[0]["postseason"].get("games_in_series") or len(remaining_games)
    wins_needed = games_in_series // 2 + 1
    series_games = [g for g in postseason.get("games", []) if g["postseason"]["series"] == postseason["series"]]
    us_wins = sum(1 for g in series_games if g["won"])
    them_wins = len(series_games) - us_wins

    per_game = [game_win_probability(p_us, p_them, g["home_or_away"] == "home") for g in remaining_games]
    return {
        "series": postseason["series"],
        "series_win_probability": round(series_win_probability(per_game, us_wins, them_wins, wins_needed), 3),
        "next_game_win_probability": round(per_game[0], 3),
        "inputs": {
            "us_true_talent": round(p_us, 3),
            "them_true_talent": round(p_them, 3),
            "home_field": HOME_FIELD,
            "wins_needed": wins_needed,
            "series_score": [us_wins, them_wins],
        },
    }
