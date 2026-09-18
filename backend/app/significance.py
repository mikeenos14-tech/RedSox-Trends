from __future__ import annotations

import asyncio

import httpx

from . import config, game_recap, mlb_client

BASE_URL = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FenwayAlmanacDashboard/1.0)"}

# Round-number thresholds worth a callout when a career total crosses them
# in today's game — never an arbitrary "impressive-sounding" cutoff.
MILESTONE_THRESHOLDS = {
    "hits": [100, 200, 300, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000],
    "homeRuns": [10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600],
    "rbi": [100, 250, 500, 750, 1000, 1500, 2000],
    "strikeOuts": [100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000],
    "wins": [10, 25, 50, 75, 100, 150, 200],
    "saves": [10, 25, 50, 100, 150, 200, 300],
}
MILESTONE_LABELS = {
    "hits": "career hits",
    "homeRuns": "career home runs",
    "rbi": "career RBI",
    "strikeOuts": "career strikeouts",
    "wins": "career wins",
    "saves": "career saves",
}

# A streak only gets called out at these lengths (extending) so a routine
# "hit safely in 6 straight" doesn't fire every single game once past the
# floor — only at genuinely round, broadcast-nameable numbers.
STREAK_MIN = 5
STREAK_CALLOUT_LENGTHS = {5, 10, 15, 20, 25, 30}

MULTI_HR_THRESHOLD = 2
BIG_HIT_THRESHOLD = 4
BIG_K_THRESHOLD = 10
SCORELESS_IP_THRESHOLD = 6.0


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    resp = await client.get(url, params=params, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


async def get_game_log(client: httpx.AsyncClient, player_id: int, season: int, group: str) -> list[dict]:
    data = await _fetch_json(
        client, f"{BASE_URL}/people/{player_id}/stats", {"stats": "gameLog", "group": group, "season": season}
    )
    stats = data.get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    return sorted(splits, key=lambda g: g["date"])


async def get_career_totals(client: httpx.AsyncClient, player_id: int, group: str) -> dict:
    data = await _fetch_json(client, f"{BASE_URL}/people/{player_id}/stats", {"stats": "career", "group": group})
    stats = data.get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    return splits[0]["stat"] if splits else {}


def _trailing_streak(results_desc: list[bool]) -> int:
    """Length of the run of matching booleans at the start of `results_desc`
    (most-recent-first) — e.g. [True, True, False] -> 2."""
    if not results_desc:
        return 0
    first = results_desc[0]
    streak = 0
    for r in results_desc:
        if r != first:
            break
        streak += 1
    return streak


def _streak_finding(had_event_asc: list[bool], today_had_event: bool, extend_type: str, snap_type: str, label: str):
    """Shared logic for both hitting streaks and team win/loss streaks: given
    a chronological (ascending) list of booleans ending with today's game,
    decide whether today extended a real streak to a callout-worthy length,
    or snapped one that had reached the real floor. Returns None otherwise —
    "nothing worth mentioning" is the expected, correct result most games."""
    if not had_event_asc:
        return None

    desc = list(reversed(had_event_asc))

    if today_had_event:
        current_streak = _trailing_streak(desc)
        if current_streak in STREAK_CALLOUT_LENGTHS:
            return {"type": extend_type, "value": current_streak, "label": label}
        return None

    # today did NOT have the event. A "snapped" streak only exists if the
    # event was actually happening immediately before today — `_trailing_streak`
    # counts a run of whatever value starts the list, so it must not be
    # trusted here unless that starting value is genuinely `True`, or a run
    # of *misses* (e.g. an ongoing cold streak) would be misread as a streak
    # that just snapped.
    before_today = desc[1:]
    if not before_today or not before_today[0]:
        return None
    prior_streak = _trailing_streak(before_today)
    if prior_streak >= STREAK_MIN:
        return {"type": snap_type, "value": prior_streak, "label": label}
    return None


async def check_hitting_streak(
    client: httpx.AsyncClient, player_id: int, name: str, season: int, game_date: str
) -> dict | None:
    log = await get_game_log(client, player_id, season, "hitting")
    played = [g for g in log if g["stat"].get("plateAppearances", 0) > 0]
    # MLB's aggregated gameLog endpoint can lag a few minutes behind the
    # schedule/boxscore going Final — if it hasn't caught up yet, bail
    # rather than risk treating a prior game's line as today's.
    if not played or played[-1]["date"] != game_date:
        return None

    today_had_hit = played[-1]["stat"].get("hits", 0) > 0
    had_hit_asc = [g["stat"].get("hits", 0) > 0 for g in played]

    finding = _streak_finding(had_hit_asc, today_had_hit, "hitting_streak_extended", "hitting_streak_snapped", name)
    if not finding:
        return None
    if finding["type"] == "hitting_streak_extended":
        finding["detail"] = f"{name} has hit safely in {finding['value']} straight games."
    else:
        finding["detail"] = f"{name}'s {finding['value']}-game hitting streak has come to an end."
    return finding


async def check_multi_hit_or_hr(
    client: httpx.AsyncClient, player_id: int, name: str, season: int, game_date: str
) -> dict | None:
    log = await get_game_log(client, player_id, season, "hitting")
    if not log or log[-1]["date"] != game_date:
        return None
    today = log[-1]["stat"]
    hits = today.get("hits", 0)
    hrs = today.get("homeRuns", 0)

    if hrs >= MULTI_HR_THRESHOLD:
        count = sum(1 for g in log if g["stat"].get("homeRuns", 0) >= MULTI_HR_THRESHOLD)
        return {
            "type": "multi_hr_game",
            "value": hrs,
            "detail": f"{name} hit {hrs} home runs — his {_ordinal(count)} multi-homer game this season.",
        }
    if hits >= BIG_HIT_THRESHOLD:
        count = sum(1 for g in log if g["stat"].get("hits", 0) >= BIG_HIT_THRESHOLD)
        return {
            "type": "big_hit_game",
            "value": hits,
            "detail": f"{name} racked up {hits} hits — his {_ordinal(count)} game with {BIG_HIT_THRESHOLD}+ hits this season.",
        }
    return None


async def check_pitching_outing(
    client: httpx.AsyncClient, player_id: int, name: str, season: int, game_date: str
) -> dict | None:
    log = await get_game_log(client, player_id, season, "pitching")
    if not log or log[-1]["date"] != game_date:
        return None
    today = log[-1]["stat"]
    ip = float(today.get("inningsPitched") or 0)
    so = today.get("strikeOuts", 0)
    er = today.get("earnedRuns", 0)

    if so >= BIG_K_THRESHOLD:
        season_high = max((g["stat"].get("strikeOuts", 0) for g in log), default=0)
        if so >= season_high:
            return {
                "type": "big_strikeout_game",
                "value": so,
                "detail": f"{name} struck out {so} — a season high.",
            }
        return {
            "type": "big_strikeout_game",
            "value": so,
            "detail": f"{name} struck out {so} batters.",
        }

    if ip >= SCORELESS_IP_THRESHOLD and er == 0:
        return {
            "type": "scoreless_outing",
            "value": ip,
            "detail": f"{name} threw {today.get('inningsPitched')} scoreless innings.",
        }
    return None


async def check_batting_milestones(
    client: httpx.AsyncClient, player_id: int, name: str, season: int, game_date: str
) -> list[dict]:
    log = await get_game_log(client, player_id, season, "hitting")
    if not log or log[-1]["date"] != game_date:
        return []
    today = log[-1]["stat"]
    career = await get_career_totals(client, player_id, "hitting")

    findings = []
    for stat_key in ("hits", "homeRuns", "rbi"):
        contribution = today.get(stat_key, 0)
        after = career.get(stat_key)
        if not contribution or after is None:
            continue
        before = after - contribution
        for milestone in MILESTONE_THRESHOLDS[stat_key]:
            if before < milestone <= after:
                findings.append(
                    {
                        "type": "career_milestone",
                        "value": milestone,
                        "detail": f"{name} reached {milestone} {MILESTONE_LABELS[stat_key]}.",
                    }
                )
    return findings


async def check_pitching_milestones(
    client: httpx.AsyncClient, player_id: int, name: str, season: int, game_date: str
) -> list[dict]:
    log = await get_game_log(client, player_id, season, "pitching")
    if not log or log[-1]["date"] != game_date:
        return []
    today = log[-1]["stat"]
    career = await get_career_totals(client, player_id, "pitching")

    findings = []
    for stat_key in ("strikeOuts", "wins", "saves"):
        contribution = today.get(stat_key, 0)
        after = career.get(stat_key)
        if not contribution or after is None:
            continue
        before = after - contribution
        for milestone in MILESTONE_THRESHOLDS[stat_key]:
            if before < milestone <= after:
                findings.append(
                    {
                        "type": "career_milestone",
                        "value": milestone,
                        "detail": f"{name} reached {milestone} {MILESTONE_LABELS[stat_key]}.",
                    }
                )
    return findings


async def check_team_streak(recent_games: list[dict]) -> dict | None:
    if not recent_games:
        return None
    games_asc = sorted(recent_games, key=lambda g: g["date"])
    today_won = games_asc[-1]["won"]
    won_asc = [g["won"] for g in games_asc]

    finding = _streak_finding(won_asc, today_won, "team_streak_extended", "team_streak_snapped", "Red Sox")
    if not finding:
        return None

    # An extending streak's direction matches today's result; a snapped
    # streak's direction is the opposite of today's (the streak that ended).
    if finding["type"] == "team_streak_extended":
        word = "winning" if today_won else "losing"
        finding["detail"] = f"The Red Sox have a {finding['value']}-game {word} streak."
    else:
        word = "winning" if not today_won else "losing"
        finding["detail"] = f"The Red Sox' {finding['value']}-game {word} streak has come to an end."
    return finding


def _roster_entries(boxscore: dict, side: str) -> list[tuple[int, str, dict]]:
    """(player_id, name, stats) for every player who actually appeared —
    batted or pitched — on this side of the box score."""
    team = boxscore["teams"][side]
    entries = []
    for pid in set(team.get("batters", [])) | set(team.get("pitchers", [])):
        player = team["players"].get(f"ID{pid}")
        if not player:
            continue
        entries.append((pid, player["person"]["fullName"], player.get("stats", {})))
    return entries


async def get_game_significance(team_id: int = config.TEAM_ID, season: int = config.SEASON) -> dict | None:
    """Real, computed callouts for the team's most recently completed game —
    streaks, rare stat lines, career milestones — never an AI guess at what
    was notable. Returns None if there's no completed game to check."""
    game = await game_recap.get_last_completed_game(team_id)
    if game is None:
        return None

    game_pk = game["gamePk"]
    game_date = game["officialDate"]
    is_home = game["teams"]["home"]["team"]["id"] == team_id
    us_side = "home" if is_home else "away"

    boxscore, recent_games = await asyncio.gather(
        game_recap.get_boxscore(game_pk),
        mlb_client.get_recent_games(team_id),
    )

    entries = _roster_entries(boxscore, us_side)

    async with httpx.AsyncClient(timeout=10) as client:
        tasks = []
        for pid, name, stats in entries:
            if stats.get("batting", {}).get("atBats", 0) > 0 or stats.get("batting", {}).get("plateAppearances", 0) > 0:
                tasks.append(check_hitting_streak(client, pid, name, season, game_date))
                tasks.append(check_multi_hit_or_hr(client, pid, name, season, game_date))
                tasks.append(check_batting_milestones(client, pid, name, season, game_date))
            if stats.get("pitching", {}).get("inningsPitched"):
                tasks.append(check_pitching_outing(client, pid, name, season, game_date))
                tasks.append(check_pitching_milestones(client, pid, name, season, game_date))

        tasks.append(check_team_streak(recent_games))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    findings: list[dict] = []
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        if isinstance(r, list):
            findings.extend(r)
        else:
            findings.append(r)

    return {"game_pk": game_pk, "date": game["officialDate"], "findings": findings}
