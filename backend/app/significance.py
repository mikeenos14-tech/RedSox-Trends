from __future__ import annotations

import asyncio

import httpx

from . import config, game_recap, mlb_client
from . import http
from . import season as season_mod

BASE_URL = http.MLB_API
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
#
# Hitting streaks start at 10: at a 5-game floor, 40 real games produced
# ~30 "hit safely in 5 straight" / "5-game streak ended" callouts — routine,
# not rare. Team win/loss streaks keep the 5-game floor; a 5-game team
# streak is genuinely uncommon and broadcast-worthy.
HITTING_STREAK_MIN = 10
HITTING_STREAK_CALLOUT_LENGTHS = {10, 15, 20, 25, 30, 35, 40}
TEAM_STREAK_MIN = 5
TEAM_STREAK_CALLOUT_LENGTHS = {5, 10, 15, 20}

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


async def get_game_log(
    client: httpx.AsyncClient, player_id: int, season: int, group: str, game_types: str | None = None
) -> list[dict]:
    params = {"stats": "gameLog", "group": group, "season": season}
    if game_types:
        params["gameType"] = game_types
    data = await _fetch_json(client, f"{BASE_URL}/people/{player_id}/stats", params)
    stats = data.get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    # gameNumber breaks the tie within a doubleheader.
    return sorted(splits, key=lambda g: (g["date"], (g.get("game") or {}).get("gameNumber", 1)))


class LogNotCaughtUp(Exception):
    """MLB's aggregated gameLog endpoint can lag a few minutes behind the
    schedule/boxscore going Final. Raised (rather than returning "no
    finding") so the caller knows the result is incomplete and must not be
    cached as this game's final answer."""


def _this_game(log: list[dict], game_pk: int) -> dict:
    """The log entry for this exact game. Matched on gamePk, not date — in a
    doubleheader, a log that has only caught up through Game 1 has the right
    date but the wrong game."""
    if not log or (log[-1].get("game") or {}).get("gamePk") != game_pk:
        raise LogNotCaughtUp()
    return log[-1]


def _hit_streak_result(stat: dict) -> bool | None:
    """Official scoring rule 9.23(b): a game whose plate appearances were all
    walks, HBP, catcher's interference, or sacrifice bunts neither extends
    nor ends a hitting streak (None). A sacrifice fly with no hit does end
    it."""
    if (stat.get("hits") or 0) > 0:
        return True
    if (stat.get("atBats") or 0) == 0 and (stat.get("sacFlies") or 0) == 0:
        return None
    return False


async def get_career_totals(
    client: httpx.AsyncClient, player_id: int, group: str, postseason: bool = False
) -> dict:
    params = {"stats": "career", "group": group}
    if postseason:
        # gameType=P is career *postseason* totals. (The API's
        # "careerPlayoffs" / "yearByYearPlayoffs" stat types silently return
        # regular-season numbers — don't use them.)
        params["gameType"] = "P"
    data = await _fetch_json(client, f"{BASE_URL}/people/{player_id}/stats", params)
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


def _streak_finding(
    had_event_asc: list[bool],
    today_had_event: bool,
    extend_type: str,
    snap_type: str,
    label: str,
    min_length: int,
    callout_lengths: set[int],
):
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
        if current_streak in callout_lengths:
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
    if prior_streak >= min_length:
        return {"type": snap_type, "value": prior_streak, "label": label}
    return None


def check_hitting_streak(log: list[dict], name: str, game_pk: int) -> dict | None:
    today_result = _hit_streak_result(_this_game(log, game_pk)["stat"])
    if today_result is None:
        return None  # a walks-only day: the streak is simply paused
    results = [_hit_streak_result(g["stat"]) for g in log if (g["stat"].get("plateAppearances") or 0) > 0]
    had_hit_asc = [r for r in results if r is not None]
    today_had_hit = today_result

    finding = _streak_finding(
        had_hit_asc, today_had_hit, "hitting_streak_extended", "hitting_streak_snapped", name,
        HITTING_STREAK_MIN, HITTING_STREAK_CALLOUT_LENGTHS,
    )
    if not finding:
        return None
    if finding["type"] == "hitting_streak_extended":
        finding["detail"] = f"{name} has hit safely in {finding['value']} straight games."
    else:
        finding["detail"] = f"{name}'s {finding['value']}-game hitting streak has come to an end."
    return finding


def check_multi_hit_or_hr(log: list[dict], name: str, game_pk: int) -> dict | None:
    today = _this_game(log, game_pk)["stat"]
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


def check_pitching_outing(log: list[dict], name: str, game_pk: int) -> dict | None:
    today = _this_game(log, game_pk)["stat"]
    ip = float(today.get("inningsPitched") or 0)
    so = today.get("strikeOuts", 0)
    er = today.get("earnedRuns", 0)

    if so >= BIG_K_THRESHOLD:
        season_high = max((g["stat"].get("strikeOuts", 0) for g in log), default=0)
        if so >= season_high:
            # A tie with an earlier start is "matched," not "a season high."
            tied = sum(1 for g in log if g["stat"].get("strikeOuts", 0) == so) > 1
            return {
                "type": "big_strikeout_game",
                "value": so,
                "detail": f"{name} struck out {so} — {'matching his season high' if tied else 'a season high'}.",
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
    client: httpx.AsyncClient, player_id: int, name: str, log: list[dict], game_pk: int
) -> list[dict]:
    today = _this_game(log, game_pk)["stat"]
    if not any(today.get(k) for k in ("hits", "homeRuns", "rbi")):
        return []
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
    client: httpx.AsyncClient, player_id: int, name: str, log: list[dict], game_pk: int
) -> list[dict]:
    today = _this_game(log, game_pk)["stat"]
    if not any(today.get(k) for k in ("strikeOuts", "wins", "saves")):
        return []
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

    finding = _streak_finding(
        won_asc, today_won, "team_streak_extended", "team_streak_snapped", "Red Sox",
        TEAM_STREAK_MIN, TEAM_STREAK_CALLOUT_LENGTHS,
    )
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


# --- postseason checks ----------------------------------------------------------------
#
# Same rules as the regular-season checks: real data, hard thresholds,
# nothing reported when nothing notable happened. "Career postseason" facts
# come from MLB's career totals with gameType=P; the value *before* this game
# is that total minus this game and any later postseason games this season,
# so it's right whether the game is the latest one or a replay.

POSTSEASON_MILESTONES = {
    "homeRuns": [5, 10, 15, 20, 25],
    "hits": [25, 50, 75, 100],
    "rbi": [25, 50, 75],
    "strikeOuts": [25, 50, 75, 100, 150, 200],
}
POSTSEASON_MILESTONE_LABELS = {
    "homeRuns": "career postseason home runs",
    "hits": "career postseason hits",
    "rbi": "career postseason RBI",
    "strikeOuts": "career postseason strikeouts",
}
NUMBER_WORDS = {2: "twice", 3: "three times", 4: "four times"}


def _entry_index(log: list[dict], game_pk: int) -> int:
    for i, g in enumerate(log):
        if (g.get("game") or {}).get("gamePk") == game_pk:
            return i
    raise LogNotCaughtUp()


def _career_before_and_after(career: dict, log: list[dict], idx: int, key: str) -> tuple[int, int] | None:
    """(career postseason total before this game, after it). None when the
    career endpoint hasn't caught up with this season's postseason log yet."""
    total = career.get(key)
    if total is None:
        return None
    season_sum = sum(g["stat"].get(key, 0) or 0 for g in log)
    if total < season_sum:
        raise LogNotCaughtUp()  # career totals lag the game log right after a final
    later = sum(g["stat"].get(key, 0) or 0 for g in log[idx + 1 :])
    after = total - later
    return after - (log[idx]["stat"].get(key, 0) or 0), after


def _postseason_milestones(career: dict, log: list[dict], idx: int, keys: list[str], name: str) -> list[dict]:
    findings = []
    for key in keys:
        span = _career_before_and_after(career, log, idx, key)
        if not span:
            continue
        before, after = span
        for milestone in POSTSEASON_MILESTONES[key]:
            if before < milestone <= after:
                findings.append(
                    {
                        "type": "postseason_milestone",
                        "value": milestone,
                        "detail": f"{name} reached {milestone} {POSTSEASON_MILESTONE_LABELS[key]}.",
                    }
                )
    return findings


def check_postseason_hitting(log: list[dict], career: dict, name: str, game_pk: int) -> list[dict]:
    idx = _entry_index(log, game_pk)
    today = log[idx]["stat"]
    hrs, hits = today.get("homeRuns", 0) or 0, today.get("hits", 0) or 0
    findings = []

    hr_span = _career_before_and_after(career, log, idx, "homeRuns") if hrs else None
    first_hr = bool(hr_span) and hr_span[0] == 0
    if hrs >= MULTI_HR_THRESHOLD:
        tail = " — the first postseason home runs of his career" if first_hr else ""
        findings.append({"type": "postseason_multi_hr", "value": hrs, "detail": f"{name} homered {NUMBER_WORDS.get(hrs, f'{hrs} times')}{tail}."})
    elif first_hr:
        findings.append({"type": "first_postseason_hr", "value": 1, "detail": f"{name} hit his first career postseason home run."})
    if hits >= BIG_HIT_THRESHOLD:
        findings.append({"type": "postseason_big_hit_game", "value": hits, "detail": f"{name} had {hits} hits."})

    keys = [k for k in ("homeRuns", "hits", "rbi") if today.get(k)]
    findings.extend(_postseason_milestones(career, log, idx, keys, name))
    return findings


def check_postseason_pitching(log: list[dict], career: dict, name: str, game_pk: int) -> list[dict]:
    idx = _entry_index(log, game_pk)
    today = log[idx]["stat"]
    so = today.get("strikeOuts", 0) or 0
    ip = float(today.get("inningsPitched") or 0)
    started = (today.get("gamesStarted") or 0) > 0
    findings = []

    if so >= BIG_K_THRESHOLD:
        findings.append({"type": "postseason_big_k", "value": so, "detail": f"{name} struck out {so}{' in a postseason start' if started else ''}."})
    elif ip >= SCORELESS_IP_THRESHOLD and (today.get("earnedRuns") or 0) == 0 and (today.get("runs") or 0) == 0:
        findings.append({"type": "postseason_scoreless", "value": ip, "detail": f"{name} threw {today.get('inningsPitched')} scoreless innings."})

    for key, label in (("wins", "win"), ("saves", "save")):
        if today.get(key):
            span = _career_before_and_after(career, log, idx, key)
            if span and span[0] == 0:
                findings.append({"type": f"first_postseason_{label}", "value": 1, "detail": f"{name} earned his first career postseason {label}."})

    if so:
        findings.extend(_postseason_milestones(career, log, idx, ["strikeOuts"], name))
    return findings


def check_series_outcome(game: dict, team_id: int) -> dict | None:
    """Clinch, elimination, or forcing a decisive final game — the series
    facts, stated from MLB's own series status (never computed here)."""
    ps = mlb_client.postseason_info(game)
    if not ps or not ps["status"]:
        return None
    if ps["is_over"]:
        if ps["winning_team_id"] == team_id:
            return {"type": "series_clinched", "value": 1, "detail": f"The Red Sox won the {ps['series']} ({ps['status']})."}
        return {"type": "series_eliminated", "value": 1, "detail": f"The Red Sox were eliminated from the {ps['series']} ({ps['status']})."}
    games_in_series = ps.get("games_in_series") or 0
    if "tied" in ps["status"].lower() and ps.get("game_number") == games_in_series - 1:
        return {"type": "series_forced_decider", "value": games_in_series, "detail": f"The Red Sox forced a decisive Game {games_in_series} ({ps['status']})."}
    return None


async def get_postseason_significance(game: dict, team_id: int, season: int) -> dict:
    game_pk = game["gamePk"]
    is_home = game["teams"]["home"]["team"]["id"] == team_id
    boxscore = await game_recap.get_boxscore(game_pk)
    entries = _roster_entries(boxscore, "home" if is_home else "away")
    hitters = [(pid, name) for pid, name, st in entries if (st.get("batting", {}).get("plateAppearances") or 0) > 0]
    pitchers = [(pid, name) for pid, name, st in entries if st.get("pitching", {}).get("inningsPitched")]
    post_types = ",".join(config.POSTSEASON_GAME_TYPES)

    complete = True
    findings: list[dict] = []

    async def run(pid, name, group, check):
        nonlocal complete
        try:
            log, career = await asyncio.gather(
                get_game_log(client, pid, season, group, game_types=post_types),
                get_career_totals(client, pid, group, postseason=True),
            )
            findings.extend(check(log, career, name, game_pk))
        except LogNotCaughtUp:
            complete = False
        except httpx.HTTPError:
            pass  # one player's fetch failing shouldn't sink the rest

    async with http.session(timeout=10) as client:
        await asyncio.gather(
            *(run(pid, name, "hitting", check_postseason_hitting) for pid, name in hitters),
            *(run(pid, name, "pitching", check_postseason_pitching) for pid, name in pitchers),
        )

    series = check_series_outcome(game, team_id)
    if series:
        findings.insert(0, series)
    return {"game_pk": game_pk, "date": game["officialDate"], "findings": findings, "complete": complete}


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


async def get_game_significance(
    team_id: int = config.TEAM_ID, season: int | None = None, game: dict | None = None
) -> dict | None:
    """Real, computed callouts for the team's most recently completed game —
    streaks, rare stat lines, career milestones — never an AI guess at what
    was notable. Returns None if there's no completed game to check.

    `complete` is False when any player's game log hadn't caught up to this
    game yet — the result is then partial and must not be cached as final.
    Accepts an already-fetched `game` so the caller can check its own cache
    by gamePk before paying for any of this."""
    season = season or season_mod.current()
    if game is None:
        game = await game_recap.get_last_completed_game(team_id)
    if game is None:
        return None

    game_pk = game["gamePk"]
    game_date = game["officialDate"]

    # The regular-season checks below rest on regular-season logs, season
    # counts, and streaks; a playoff game gets its own set instead.
    if mlb_client.postseason_info(game):
        return await get_postseason_significance(game, team_id, season)
    is_home = game["teams"]["home"]["team"]["id"] == team_id
    us_side = "home" if is_home else "away"

    boxscore, recent_games = await asyncio.gather(
        game_recap.get_boxscore(game_pk),
        mlb_client.get_recent_games(team_id),
    )

    entries = _roster_entries(boxscore, us_side)

    hitters = [
        (pid, name)
        for pid, name, stats in entries
        if stats.get("batting", {}).get("atBats", 0) > 0 or stats.get("batting", {}).get("plateAppearances", 0) > 0
    ]
    pitchers = [(pid, name) for pid, name, stats in entries if stats.get("pitching", {}).get("inningsPitched")]

    complete = True
    findings: list[dict] = []

    def collect(result) -> None:
        nonlocal complete
        if isinstance(result, LogNotCaughtUp):
            complete = False
        elif isinstance(result, list):
            findings.extend(result)
        elif isinstance(result, dict):
            findings.append(result)
        # Any other exception (a transient fetch failure for one player) is
        # skipped — one missing check shouldn't sink the rest.

    async with http.session(timeout=10) as client:
        # One game-log fetch per player, shared by every check that needs it.
        hit_logs, pitch_logs = await asyncio.gather(
            asyncio.gather(*(get_game_log(client, pid, season, "hitting") for pid, _ in hitters), return_exceptions=True),
            asyncio.gather(*(get_game_log(client, pid, season, "pitching") for pid, _ in pitchers), return_exceptions=True),
        )

        milestone_tasks = []
        for (pid, name), log in zip(hitters, hit_logs):
            if isinstance(log, Exception):
                continue
            for check in (check_hitting_streak, check_multi_hit_or_hr):
                try:
                    collect(check(log, name, game_pk))
                except LogNotCaughtUp as exc:
                    collect(exc)
            milestone_tasks.append(check_batting_milestones(client, pid, name, log, game_pk))
        for (pid, name), log in zip(pitchers, pitch_logs):
            if isinstance(log, Exception):
                continue
            try:
                collect(check_pitching_outing(log, name, game_pk))
            except LogNotCaughtUp as exc:
                collect(exc)
            milestone_tasks.append(check_pitching_milestones(client, pid, name, log, game_pk))

        for r in await asyncio.gather(*milestone_tasks, return_exceptions=True):
            collect(r)

    collect(await check_team_streak(recent_games))

    return {"game_pk": game_pk, "date": game["officialDate"], "findings": findings, "complete": complete}
