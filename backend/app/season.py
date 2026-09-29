"""Which MLB season the site is showing, resolved from MLB's own calendar
instead of a hard-coded year — so the site rolls over to a new season on
its own each spring, with no code change and no redeploy.

Rule: show a season from its Opening Day until the next season's Opening
Day. MLB's API flips its "current season" on January 1, which would leave
every page empty from New Year's to late March — so before a season's
regular season starts, the previous (completed) season stays on screen.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

from . import config
from . import http

logger = logging.getLogger("uvicorn.error")

SEASONS_URL = "https://statsapi.mlb.com/api/v1/seasons"


def _guess(today: date) -> dict:
    # Used only until the first successful MLB lookup (or if it fails):
    # Opening Day is always late March / early April.
    year = today.year if (today.month, today.day) >= (3, 25) else today.year - 1
    return {
        "season": year,
        "regular_start": date(year, 3, 25),
        "regular_end": date(year, 9, 30),
        "season_end": date(year, 11, 5),
    }


_state: dict = {"info": _guess(config.eastern_today()), "checked_on": None}
_lock = asyncio.Lock()


def current() -> int:
    return _state["info"]["season"]


def anchor_date() -> date:
    """"Today," clamped to the shown season's last day — so a lookback like
    "the last 45 days" or "the most recent game" still finds the season's
    final games all winter instead of coming up empty."""
    return min(config.eastern_today(), _state["info"]["season_end"])


def regular_season_over() -> bool:
    return config.eastern_today() > _state["info"]["regular_end"]


def start_date() -> date:
    """The shown season's first possible game date (spring training aside) —
    a lookback must never reach into the previous season's games."""
    return _state["info"]["regular_start"]


async def _fetch(client: httpx.AsyncClient, season: int | None) -> dict:
    url = f"{SEASONS_URL}/{season}" if season else SEASONS_URL
    resp = await client.get(url, params={"sportId": 1})
    resp.raise_for_status()
    s = resp.json()["seasons"][0]
    return {
        "season": int(s["seasonId"]),
        "regular_start": date.fromisoformat(s["regularSeasonStartDate"]),
        "regular_end": date.fromisoformat(s["regularSeasonEndDate"]),
        "season_end": date.fromisoformat(s.get("postSeasonEndDate") or s["seasonEndDate"]),
    }


async def ensure_fresh() -> None:
    """Re-resolve the season at most once per Eastern day. Never raises — a
    failed lookup keeps the last known (or guessed) season."""
    today = config.eastern_today()
    if _state["checked_on"] == today:
        return
    async with _lock:
        if _state["checked_on"] == today:
            return
        try:
            async with http.session(timeout=10) as client:
                info = await _fetch(client, None)
                if today < info["regular_start"]:
                    info = await _fetch(client, info["season"] - 1)
            if info["season"] != _state["info"]["season"]:
                logger.info("Showing MLB season %s", info["season"])
            _state["info"] = info
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            logger.warning("Season lookup failed, keeping %s: %s", current(), exc)
        _state["checked_on"] = today
