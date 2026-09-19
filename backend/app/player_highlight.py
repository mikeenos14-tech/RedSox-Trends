from __future__ import annotations

import hashlib
from datetime import date, datetime

import httpx

from . import config, player_stats

BASE_URL = "https://statsapi.mlb.com/api/v1"


def eastern_today() -> date:
    return datetime.now(config.EASTERN_TZ).date()


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


async def get_person_bio(person_id: int) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/people/{person_id}")
        resp.raise_for_status()
        data = resp.json()
    people = data.get("people") or []
    return people[0] if people else {}


async def get_draft_info(person_id: int, draft_year: int | None) -> dict | None:
    """Real drafting team/round/pick/school, when the player was drafted
    (vs. signed as an international free agent, which has no draft record).
    This is exactly the kind of specific claim ('drafted by the Yankees')
    that shouldn't be left to the model to recall from memory when a
    verifiable source exists."""
    if not draft_year:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BASE_URL}/draft/{draft_year}", params={"playerId": person_id})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return None

    for rnd in data.get("drafts", {}).get("rounds", []):
        for pick in rnd.get("picks", []):
            if pick.get("person", {}).get("id") == person_id:
                school = pick.get("school") or {}
                return {
                    "team": (pick.get("team") or {}).get("name"),
                    "round": pick.get("pickRound"),
                    "pick_number": pick.get("pickNumber"),
                    "school_name": school.get("name"),
                    "school_location": ", ".join(p for p in [school.get("city"), school.get("state") or school.get("country")] if p) or None,
                }
    return None


async def get_stat_lines(person_id: int, season: int = config.SEASON) -> dict:
    """Real season + career stat lines (whichever of hitting/pitching applies
    to this player) — grounds 'what they've been doing' in actual numbers
    instead of vague narrative filler."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BASE_URL}/people/{person_id}/stats",
                params={"stats": "season,career", "group": "hitting,pitching", "season": season},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return {}

    def first_split(stat_type: str, group: str) -> dict | None:
        for block in data.get("stats", []):
            if block["type"]["displayName"] == stat_type and block["group"]["displayName"] == group:
                splits = block.get("splits", [])
                return splits[0]["stat"] if splits else None
        return None

    hitting_season = first_split("season", "hitting")
    hitting_career = first_split("career", "hitting")
    pitching_season = first_split("season", "pitching")
    pitching_career = first_split("career", "pitching")

    result: dict = {}
    if hitting_season and (hitting_season.get("plateAppearances") or 0) > 0:
        result["hitting_this_season"] = {
            "avg": hitting_season.get("avg"),
            "hr": hitting_season.get("homeRuns"),
            "rbi": hitting_season.get("rbi"),
            "ops": hitting_season.get("ops"),
            "games": hitting_season.get("gamesPlayed"),
        }
        if hitting_career:
            result["hitting_career"] = {
                "avg": hitting_career.get("avg"),
                "hr": hitting_career.get("homeRuns"),
                "rbi": hitting_career.get("rbi"),
                "ops": hitting_career.get("ops"),
                "games": hitting_career.get("gamesPlayed"),
            }
    if pitching_season and (pitching_season.get("inningsPitched") or "0") != "0.0":
        result["pitching_this_season"] = {
            "era": pitching_season.get("era"),
            "wins": pitching_season.get("wins"),
            "losses": pitching_season.get("losses"),
            "saves": pitching_season.get("saves"),
            "strikeouts": pitching_season.get("strikeOuts"),
            "innings_pitched": pitching_season.get("inningsPitched"),
        }
        if pitching_career:
            result["pitching_career"] = {
                "era": pitching_career.get("era"),
                "wins": pitching_career.get("wins"),
                "losses": pitching_career.get("losses"),
                "saves": pitching_career.get("saves"),
                "strikeouts": pitching_career.get("strikeOuts"),
                "innings_pitched": pitching_career.get("inningsPitched"),
            }
    return result


# Nicknames confirmed from a real, specific, citable source (not the model's
# own recollection) — see the comment on each entry. Only add to this list
# when you've actually verified it; leaving it out defaults to the AI's own
# (deliberately cautious) judgment call, which is the safer default at scale.
KNOWN_NICKNAMES: dict[int, str] = {
    678011: "Tony Seagulls",  # per the Red Sox's own Instagram: "Seigler stays loving the Tony Seagulls nickname"
    676979: "The Pig",  # Crochet himself confirmed he likes it (Sportskeeda: "I like the pig nickname... my wife thinks it's hilarious"); widely used by Red Sox fans/media since his trade to Boston
    807799: "Macho Man",  # from his Village People walk-up song in Japan (NPB); fans still wave inflatable dumbbells for him now (NESN, Nippon.com)
    547973: "The Cuban Missile",  # his defining nickname for over a decade, tied to his fastball velocity and Cuban heritage (Bleacher Report, Dallas News, and many others)
    668939: "Clutchman",  # earned at the 2018 College World Series with Oregon State; still widely used (multiple dedicated write-ups)
    624133: "The Cooler",  # his agent Scott Boras's nickname for him, highlighting his composure and consistency on the mound
    643396: "Hawaiian Hustle",  # tied to his Honolulu, HI birthplace and his all-out style of play
    701350: "Roman Empire",  # obvious pun on his first name, used since his 2025 MLB debut
}


async def get_daily_highlight(for_date: date | None = None) -> dict:
    for_date = for_date or eastern_today()

    roster = await player_stats.get_roster()
    position_by_id = {
        entry["person"]["id"]: entry.get("position", {}).get("abbreviation") for entry in roster
    }

    person_id = _pick_daily_player_id(roster, for_date)
    bio = await get_person_bio(person_id)
    draft_info = await get_draft_info(person_id, bio.get("draftYear"))
    stat_lines = await get_stat_lines(person_id)

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
        "drafted_by": draft_info.get("team") if draft_info else None,
        "draft_round": draft_info.get("round") if draft_info else None,
        "draft_pick_number": draft_info.get("pick_number") if draft_info else None,
        "draft_school": draft_info.get("school_name") if draft_info else None,
        "draft_school_location": draft_info.get("school_location") if draft_info else None,
        "verified_nickname": KNOWN_NICKNAMES.get(person_id),
        "mlb_debut": bio.get("mlbDebutDate"),
        "headshot_url": f"https://midfield.mlbstatic.com/v1/people/{person_id}/spots/240",
        **stat_lines,
    }
