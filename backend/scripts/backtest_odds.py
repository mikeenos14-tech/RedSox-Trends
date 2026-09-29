"""Backtest app/odds.py's per-game model against real postseason results.

    cd backend && venv/bin/python -m scripts.backtest_odds [first_season] [last_season]

Scores each game's pregame home-win probability (team strength from that
season's final regular-season runs) with the Brier score, against a coin
flip (0.250) and a flat "home team wins 54%" baseline. A model must beat
the coin flip here before its output goes on the site.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from app import odds

API = "https://statsapi.mlb.com/api/v1"


async def season_games(client: httpx.AsyncClient, season: int) -> list[tuple]:
    strength = {}
    for league in (103, 104):
        data = (await client.get(f"{API}/standings", params={"leagueId": league, "season": season, "standingsTypes": "regularSeason"})).json()
        for division in data["records"]:
            for t in division["teamRecords"]:
                lr = t["leagueRecord"]
                strength[t["team"]["id"]] = odds.true_talent(t["runsScored"], t["runsAllowed"], lr["wins"] + lr["losses"])
    sched = (await client.get(f"{API}/schedule", params={"sportId": 1, "season": season, "gameType": "F,D,L,W"})).json()
    rows = []
    for date in sched["dates"]:
        for g in date["games"]:
            if g["status"]["codedGameState"] != "F":
                continue
            home, away = g["teams"]["home"], g["teams"]["away"]
            p = odds.game_win_probability(strength[home["team"]["id"]], strength[away["team"]["id"]], us_home=True)
            rows.append((p, 1.0 if home.get("isWinner") else 0.0))
    return rows


async def main(first: int, last: int) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        rows = [r for season in range(first, last + 1) for r in await season_games(client, season)]
    n = len(rows)
    brier = sum((p - y) ** 2 for p, y in rows) / n
    home = sum((0.54 - y) ** 2 for _, y in rows) / n
    favorite = sum(1 for p, y in rows if (p > 0.5) == (y == 1.0)) / n
    print(f"{first}-{last}: {n} games | Brier model {brier:.4f}, home-54% {home:.4f}, coin 0.2500 | favorite won {favorite:.1%}")
    print("BEATS COIN FLIP" if brier < 0.2475 else "does not meaningfully beat a coin flip — do not publish")


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:3]] or [2021, 2025]
    asyncio.run(main(args[0], args[1] if len(args) > 1 else args[0]))
