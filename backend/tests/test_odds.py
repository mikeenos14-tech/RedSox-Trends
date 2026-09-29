"""Series-odds math (the model is backtested, and deliberately not shown on
the site — see app/odds.py)."""
from __future__ import annotations

import pytest

from app import odds


def test_even_teams_neutral_site_is_a_coin_flip():
    assert odds.log5(0.55, 0.55) == pytest.approx(0.5)


def test_home_field_is_symmetric():
    home = odds.game_win_probability(0.5, 0.5, us_home=True)
    away = odds.game_win_probability(0.5, 0.5, us_home=False)
    assert home == pytest.approx(odds.HOME_FIELD) and home + away == pytest.approx(1.0)


def test_regression_pulls_toward_500():
    raw = odds.pythagorean(739, 601)
    assert 0.5 < odds.true_talent(739, 601, 161) < raw


def test_series_math_exact_cases():
    # Coin-flip best-of-3 from 0-0 is 50%; up 1-0 it's 75%; down 0-1, 25%.
    assert odds.series_win_probability([0.5] * 3, 0, 0, 2) == pytest.approx(0.5)
    assert odds.series_win_probability([0.5] * 2, 1, 0, 2) == pytest.approx(0.75)
    assert odds.series_win_probability([0.5] * 2, 0, 1, 2) == pytest.approx(0.25)
    # Best-of-3 at p=0.6 each: p^2 + 2 p^2 (1-p) = 0.648
    assert odds.series_win_probability([0.6] * 3, 0, 0, 2) == pytest.approx(0.648)
    assert odds.series_win_probability([0.6], 2, 0, 2) == 1.0
