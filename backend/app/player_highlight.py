from __future__ import annotations

import hashlib
from datetime import date

import httpx

from . import config, player_stats

BASE_URL = "https://statsapi.mlb.com/api/v1"


def _pick_daily_player_id(roster: list[dict], for_date: date) -> int:
    """Deterministic daily pick — same player all day for every visitor,
    a new one the next day. Hashing the date (rather than e.g. day-of-year
    modulo roster size) avoids the rotation just marching through the
    roster in jersey-number order."""
    ids = sorted(entry["person"]["id"] for entry in roster)
    if not ids:
        raise ValueError("Roster is empty")
    digest = hashlib.sha256(for_date.isoformat().encode()).hexdigest()
    index = int(digest, 16) % len(ids)
    return ids[index]


async def _get_person_bio(person_id: int) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/people/{person_id}")
        resp.raise_for_status()
        data = resp.json()
    people = data.get("people") or []
    return people[0] if people else {}


async def get_daily_highlight(for_date: date | None = None) -> dict:
    for_date = for_date or date.today()

    roster = await player_stats.get_roster()
    position_by_id = {
        entry["person"]["id"]: entry.get("position", {}).get("abbreviation") for entry in roster
    }

    person_id = _pick_daily_player_id(roster, for_date)
    bio = await _get_person_bio(person_id)

    bat_side = (bio.get("batSide") or {}).get("description")
    pitch_hand = (bio.get("pitchHand") or {}).get("description")

    birthplace_parts = [
        bio.get("birthCity"),
        bio.get("birthStateProvince") if bio.get("birthCountry") == "USA" else bio.get("birthCountry"),
    ]
    birthplace = ", ".join(p for p in birthplace_parts if p)

    return {
        "date": for_date.isoformat(),
        "id": person_id,
        "name": bio.get("fullName"),
        "position": position_by_id.get(person_id) or (bio.get("primaryPosition") or {}).get("abbreviation"),
        "jersey_number": bio.get("primaryNumber"),
        "age": bio.get("currentAge"),
        "birthplace": birthplace or None,
        "height": bio.get("height"),
        "weight": bio.get("weight"),
        "bat_side": bat_side,
        "pitch_hand": pitch_hand,
        "draft_year": bio.get("draftYear"),
        "mlb_debut": bio.get("mlbDebutDate"),
        "headshot_url": f"https://midfield.mlbstatic.com/v1/people/{person_id}/spots/240",
    }
