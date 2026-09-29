"""Refresh the real-API fixtures the test suite runs against.

The tests never touch the network; they replay these captured MLB Stats API
responses. Re-run this only when you deliberately want new fixtures (e.g. to
capture a new edge case), then re-run the suite:

    cd backend && venv/bin/python -m tests.capture_fixtures
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app import game_recap

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://statsapi.mlb.com/api/v1"

RAW = {
    # 2025 BOS-NYY AL Wild Card Series: Game 1 win, Games 2-3 losses.
    "postseason_2025.json": (
        f"{API}/schedule",
        {"teamId": 111, "season": 2025, "sportId": 1, "gameType": "F,D,L,W", "hydrate": "linescore,seriesStatus"},
    ),
    # 2026 AL Wild Card Series as scheduled (Game 3 is "if necessary").
    "upcoming_2026_wc.json": (
        f"{API}/schedule",
        {
            "teamId": 111,
            "startDate": "2026-09-29",
            "endDate": "2026-10-29",
            "sportId": 1,
            "gameType": "R,F,D,L,W",
            "hydrate": "probablePitcher,seriesStatus",
        },
    ),
    # Contains a suspended game resumed the next day (gamePk 777294 listed on
    # both Jul 1 and Jul 2, 2025).
    "schedule_2025_suspended.json": (
        f"{API}/schedule",
        {
            "teamId": 111,
            "startDate": "2025-06-28",
            "endDate": "2025-07-03",
            "sportId": 1,
            "gameType": "R",
            "hydrate": "linescore,seriesStatus",
        },
    ),
    "seasons_2025.json": (f"{API}/seasons/2025", {"sportId": 1}),
    "seasons_2026.json": (f"{API}/seasons/2026", {"sportId": 1}),
}


async def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=30) as client:
        for name, (url, params) in RAW.items():
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            (FIXTURES / name).write_text(json.dumps(resp.json(), indent=1))
            print("wrote", name)

        # The fully assembled recap payload for the 9/27/2026 Cubs game (the
        # one whose AI recap miscounted runs before the fact-sheet rewrite).
        sched = (
            await client.get(
                f"{API}/schedule",
                params={"teamId": 111, "date": "2026-09-27", "sportId": 1, "hydrate": "linescore,decisions,seriesStatus"},
            )
        ).json()
    game = sched["dates"][0]["games"][0]
    data = await game_recap.get_last_game_recap_data(game=game)
    (FIXTURES / "recap_824705.json").write_text(json.dumps(data, indent=1))
    print("wrote recap_824705.json")


if __name__ == "__main__":
    asyncio.run(main())
