import asyncio
import hashlib
import json
import logging
import time
import traceback
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (
    ai_recap,
    bullpen,
    game_recap,
    league_context,
    live_game,
    mlb_client,
    news,
    on_this_day,
    player_highlight,
    player_profile,
    player_stats,
    significance,
    statcast,
    trends,
    win_probability,
)

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="The Fenway Almanac")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

HEADLINE_CACHE_SECONDS = 3600
_headline_cache = {"text": None, "generated_at": 0.0}
_highlight_cache = {"date": None, "data": None}
_highlight_lock = asyncio.Lock()
_player_profile_cache: dict[int, dict] = {}
_player_profile_lock = asyncio.Lock()
_headline_lock = asyncio.Lock()
_game_recap_cache = {"game_pk": None, "data": None}
_game_recap_lock = asyncio.Lock()
_statcast_cache = {"date": None, "data": None}
_statcast_lock = asyncio.Lock()
_league_data_cache = {"date": None, "data": None}
_league_data_lock = asyncio.Lock()
_statcast_notes_cache = {"date": None, "text": None}
_statcast_notes_lock = asyncio.Lock()
_on_this_day_cache = {"date": None, "data": None}
_on_this_day_lock = asyncio.Lock()

T = TypeVar("T")


def _stable_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


async def _cached_by_hash(cache: dict, lock: asyncio.Lock, input_data, compute: Callable[[], Awaitable[T]]) -> T:
    """Re-runs `compute` only when `input_data` has changed since the last
    call — used for the paid AI-generation endpoints. The underlying stats
    are free to re-fetch, so checking whether anything actually changed
    costs nothing; only the Claude call itself is worth avoiding. This is
    strictly better than a time-based TTL here: a timer would still force a
    regeneration on a schedule even when nothing changed (wasted tokens for
    a differently-worded rehash of the same facts), while hashing the input
    only ever calls Claude when there's something new to say.
    """
    input_hash = _stable_hash(input_data)
    async with lock:
        if cache.get("hash") == input_hash and cache.get("result") is not None:
            return cache["result"]
        result = await compute()
        cache["hash"] = input_hash
        cache["result"] = result
        return result


async def _cached_for(cache: dict, lock: asyncio.Lock, seconds: float, compute: Callable[[], Awaitable[T]]) -> T:
    """Short time-based cache for endpoints with no AI cost but a heavier
    free-API fetch (e.g. aggregating all 30 MLB teams, or every roster
    player's game log) — avoids redoing that work for every visitor within
    the same short window, without needing to know exactly when the
    underlying data changes."""
    now = time.monotonic()
    async with lock:
        if cache.get("result") is not None and (now - cache.get("fetched_at", 0.0)) < seconds:
            return cache["result"]
        result = await compute()
        cache["result"] = result
        cache["fetched_at"] = now
        return result


HEAVY_FETCH_CACHE_SECONDS = 1800  # 30 min — see _cached_for

_analysis_cache: dict = {"hash": None, "result": None}
_analysis_lock = asyncio.Lock()
_headlines_summary_cache: dict = {"hash": None, "result": None}
_headlines_summary_lock = asyncio.Lock()
_player_notes_cache: dict = {"hash": None, "result": None}
_player_notes_lock = asyncio.Lock()
_win_prob_cache = {"game_pk": None, "data": None}
_win_prob_lock = asyncio.Lock()
_significance_cache = {"game_pk": None, "data": None}
_significance_lock = asyncio.Lock()

_league_context_cache: dict = {"result": None, "fetched_at": 0.0}
_league_context_lock = asyncio.Lock()
_stat_benchmarks_cache: dict = {"result": None, "fetched_at": 0.0}
_stat_benchmarks_lock = asyncio.Lock()
_hot_cold_cache: dict = {"result": None, "fetched_at": 0.0}
_hot_cold_lock = asyncio.Lock()
_full_roster_cache: dict = {"result": None, "fetched_at": 0.0}
_full_roster_lock = asyncio.Lock()
_season_games_cache: dict = {"result": None, "fetched_at": 0.0}
_season_games_lock = asyncio.Lock()
_headlines_cache: dict = {"result": None, "fetched_at": 0.0}
_headlines_lock = asyncio.Lock()

HEADLINES_CACHE_SECONDS = 600  # 10 min — news moves faster than season stats


async def _get_season_games_cached() -> list[dict]:
    # Upcoming Schedule and Season Series both need the full-season game
    # log; without this they'd each fetch the same ~150-game season
    # schedule from MLB Stats API independently on every single Home page
    # load.
    return await _cached_for(
        _season_games_cache, _season_games_lock, HEAVY_FETCH_CACHE_SECONDS, lambda: mlb_client.get_recent_games(days=200)
    )


async def _get_player_hot_cold_cached() -> dict:
    return await _cached_for(
        _hot_cold_cache, _hot_cold_lock, HEAVY_FETCH_CACHE_SECONDS, player_stats.get_player_hot_cold_report
    )


async def _get_full_roster_cached() -> dict:
    return await _cached_for(
        _full_roster_cache, _full_roster_lock, HEAVY_FETCH_CACHE_SECONDS, player_stats.get_full_roster_report
    )


async def _get_headlines_cached() -> list[dict]:
    # The headline list and its "Summarize Coverage" button both need the
    # same Google News RSS results; without this they'd hit it independently.
    return await _cached_for(_headlines_cache, _headlines_lock, HEADLINES_CACHE_SECONDS, news.get_recent_headlines)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full traceback server-side (visible in Render's log viewer)
    # but never expose exception internals to the client — file paths,
    # package versions, etc. shouldn't be handed to anyone who can trigger
    # an error on a public-facing app.
    logger.error("Unhandled exception on %s:\n%s", request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def _build_summary() -> dict:
    standings = await mlb_client.get_team_standings()
    games = await mlb_client.get_recent_games()
    win_pcts = await mlb_client.get_league_win_pcts()
    return trends.build_trends_summary(standings, games, win_pcts)


@app.get("/api/team/summary")
async def team_summary():
    return await _build_summary()


@app.get("/api/team/league-context")
async def team_league_context():
    return await _cached_for(
        _league_context_cache, _league_context_lock, HEAVY_FETCH_CACHE_SECONDS, league_context.get_league_context
    )


@app.get("/api/team/division-standings")
async def team_division_standings():
    return {"teams": await mlb_client.get_division_standings()}


@app.get("/api/team/stat-benchmarks")
async def team_stat_benchmarks():
    return await _cached_for(
        _stat_benchmarks_cache, _stat_benchmarks_lock, HEAVY_FETCH_CACHE_SECONDS, league_context.get_stat_benchmarks
    )


@app.get("/api/team/upcoming-schedule")
async def team_upcoming_schedule():
    games = await mlb_client.get_upcoming_games()
    division_teams = await mlb_client.get_division_standings()
    division_ids = {t["id"] for t in division_teams if not t["is_target"]}
    season_games = await _get_season_games_cached()
    season_series = mlb_client.build_season_series(season_games)

    for g in games:
        g["is_division_game"] = g["opponent_id"] in division_ids
        series = season_series.get(g["opponent_id"])
        g["season_series"] = {"wins": series["wins"], "losses": series["losses"]} if series else None

    pcts = [float(g["opponent_record"]["pct"]) for g in games if g["opponent_record"].get("pct")]
    home_count = sum(1 for g in games if g["home_or_away"] == "home")

    return {
        "games": games,
        "summary": {
            "avg_opponent_pct": round(sum(pcts) / len(pcts), 3) if pcts else None,
            "home_count": home_count,
            "away_count": len(games) - home_count,
            "division_game_count": sum(1 for g in games if g["is_division_game"]),
        },
    }


@app.get("/api/team/wildcard-standings")
async def team_wildcard_standings():
    return {"teams": await mlb_client.get_wildcard_standings()}


@app.get("/api/team/season-series")
async def team_season_series():
    games = await _get_season_games_cached()
    series = mlb_client.build_season_series(games)
    result = sorted(series.values(), key=lambda s: s["wins"] + s["losses"], reverse=True)
    return {"series": result}


@app.get("/api/team/bullpen")
async def team_bullpen():
    return {"pitchers": await bullpen.get_bullpen_report()}


@app.get("/api/team/win-probability")
async def team_win_probability():
    # The play-by-play fetch here is the heaviest single request on the
    # site (~1MB) and only actually changes when a new game completes, so
    # it's cached by gamePk exactly like Previous Game Recap — cheap to
    # check (just the schedule lookup), expensive to skip checking.
    game = await game_recap.get_last_completed_game()
    if game is None:
        return {"game": None}

    game_pk = game["gamePk"]
    async with _win_prob_lock:
        if _win_prob_cache["game_pk"] == game_pk and _win_prob_cache["data"] is not None:
            return _win_prob_cache["data"]

        data = await win_probability.get_last_game_win_probability(game=game)
        result = {"game": data}
        _win_prob_cache["game_pk"] = game_pk
        _win_prob_cache["data"] = result
        return result


@app.get("/api/team/last-game-significance")
async def team_last_game_significance():
    # Cached forever by gamePk, same as the win-probability/recap endpoints —
    # a completed game's real facts never change, so there's nothing to
    # recompute on a later request for the same game. The one AI call inside
    # (narration only, never invention) only fires on a genuine cache miss.
    async with _significance_lock:
        cached = _significance_cache["data"]
        report = await significance.get_game_significance()
        if report is None:
            return {"game_pk": None, "narration": None}

        game_pk = report["game_pk"]
        if _significance_cache["game_pk"] == game_pk and cached is not None:
            return cached

        narration = None
        if report["findings"]:
            try:
                narration = ai_recap.generate_significance_narration(report["findings"])
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        result = {"game_pk": game_pk, "date": report["date"], "narration": narration}
        _significance_cache["game_pk"] = game_pk
        _significance_cache["data"] = result
        return result


@app.get("/api/team/live-game")
async def team_live_game():
    # Deliberately uncached — this is the one endpoint on the site whose
    # whole purpose is "what's true right now," polled by the frontend
    # every ~15s while a game is in progress. Almost always returns null
    # (no game live at this moment), which is cheap: one schedule lookup.
    return {"game": await live_game.get_live_game()}


@app.get("/api/team/hero-headline")
async def team_hero_headline():
    # Cached for an hour: this is the one AI call that fires automatically
    # on every page view rather than behind a button, so an uncached version
    # would mean one paid API call per visit/refresh regardless of whether
    # the visitor does anything else. The lock prevents a burst of
    # simultaneous requests right as the cache goes stale from each kicking
    # off their own redundant (and billed) regeneration.
    now = time.monotonic()
    async with _headline_lock:
        if _headline_cache["text"] is not None and (now - _headline_cache["generated_at"]) < HEADLINE_CACHE_SECONDS:
            return {"headline": _headline_cache["text"]}

        summary = await _build_summary()
        try:
            headline = ai_recap.generate_headline(summary)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        _headline_cache["text"] = headline
        _headline_cache["generated_at"] = now
        return {"headline": headline}


@app.get("/api/team/analysis")
async def team_analysis():
    # Merged with what used to be the separate "AI Trend Recap" — both took
    # the same trend data and produced overlapping paragraphs (team status +
    # analytical read), just in two different voices. One richer paragraph
    # serves both purposes without repeating itself.
    summary = await _build_summary()
    lg_ctx = await _cached_for(
        _league_context_cache, _league_context_lock, HEAVY_FETCH_CACHE_SECONDS, league_context.get_league_context
    )
    summary["league_context"] = {k: v for k, v in lg_ctx.items() if k != "run_diff_league_chart"}

    async def compute():
        try:
            return ai_recap.generate_team_analysis(summary)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    analysis = await _cached_by_hash(_analysis_cache, _analysis_lock, summary, compute)
    return {"analysis": analysis}


@app.get("/api/team/headlines")
async def team_headlines():
    headlines = await _get_headlines_cached()
    return {"headlines": headlines}


@app.get("/api/team/headlines/summary")
async def team_headlines_summary():
    headlines = await _get_headlines_cached()
    # Only the link+title actually determine what the summary should say —
    # hash those rather than the full list (which also carries publish
    # timestamps that tick over between requests without the story lineup
    # itself having changed).
    fingerprint = [{"title": h["title"], "source": h["source"]} for h in headlines]

    async def compute():
        try:
            return ai_recap.generate_headlines_summary(headlines)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    summary = await _cached_by_hash(_headlines_summary_cache, _headlines_summary_lock, fingerprint, compute)
    return {"summary": summary}


@app.get("/api/players/hot-cold")
async def players_hot_cold():
    return await _get_player_hot_cold_cached()


@app.get("/api/players/full-roster")
async def players_full_roster():
    return await _get_full_roster_cached()


@app.get("/api/players/notes")
async def players_notes():
    report = await _get_player_hot_cold_cached()
    slim_report = player_stats.slim_for_ai(report)

    async def compute():
        try:
            return ai_recap.generate_player_notes(slim_report)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    notes = await _cached_by_hash(_player_notes_cache, _player_notes_lock, slim_report, compute)
    return {"notes": notes}


@app.get("/api/players/highlight")
async def players_highlight():
    # Cached for the calendar day (Eastern time — see
    # player_highlight.eastern_today for why): the whole point is one
    # player featured per day for everyone, not a fresh AI-written bio
    # (and roster fetch) on every visit.
    today = player_highlight.eastern_today().isoformat()
    async with _highlight_lock:
        if _highlight_cache["date"] == today and _highlight_cache["data"] is not None:
            return _highlight_cache["data"]

        bio = await player_highlight.get_daily_highlight()
        try:
            narrative = ai_recap.generate_player_highlight(bio)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        result = {**bio, "narrative": narrative}
        _highlight_cache["date"] = today
        _highlight_cache["data"] = result
        return result


@app.get("/api/players/profile")
async def players_profile(id: int):
    # Day-cached per player (Eastern) — a player's page doesn't need to
    # recompute career/game-log/Statcast data on every single visit, only
    # once the calendar day actually turns over.
    today = player_highlight.eastern_today().isoformat()
    async with _player_profile_lock:
        cached = _player_profile_cache.get(id)
        if cached and cached["date"] == today:
            return cached["data"]

        profile = await player_profile.get_player_profile(id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Player not found on the current 40-man roster")

        _player_profile_cache[id] = {"date": today, "data": profile}
        return profile


async def _get_league_data_cached() -> dict:
    # Savant recalculates percentiles once daily after games are logged, so
    # a same-day cache avoids re-scraping several leaderboard pages (no
    # official API, so being a light touch matters) on every page view —
    # shared by the team report, player search, and player comparison so
    # only the first of those hit today pays the Savant round-trip.
    today = player_highlight.eastern_today().isoformat()
    async with _league_data_lock:
        if _league_data_cache["date"] == today and _league_data_cache["data"] is not None:
            return _league_data_cache["data"]

        data = await statcast.fetch_league_data()
        _league_data_cache["date"] = today
        _league_data_cache["data"] = data
        return data


async def _get_statcast_report_cached() -> dict:
    today = player_highlight.eastern_today().isoformat()
    async with _statcast_lock:
        if _statcast_cache["date"] == today and _statcast_cache["data"] is not None:
            return _statcast_cache["data"]

        league_data = await _get_league_data_cached()
        report = await statcast.get_statcast_report(league_data)
        _statcast_cache["date"] = today
        _statcast_cache["data"] = report
        return report


@app.get("/api/players/statcast")
async def players_statcast():
    return await _get_statcast_report_cached()


@app.get("/api/players/search")
async def players_search(q: str = ""):
    league_data = await _get_league_data_cached()
    return {"results": statcast.search_players(q, league_data)}


@app.get("/api/players/compare")
async def players_compare(player_id: int, type: str):
    if type not in ("hitter", "pitcher"):
        raise HTTPException(status_code=400, detail="type must be 'hitter' or 'pitcher'")
    league_data = await _get_league_data_cached()
    profile = statcast.get_player_comparison_data(player_id, type, league_data)
    if profile is None:
        raise HTTPException(status_code=404, detail="Player not found in this year's qualifying leaderboard")
    return profile


@app.get("/api/players/statcast-notes")
async def players_statcast_notes():
    today = player_highlight.eastern_today().isoformat()
    async with _statcast_notes_lock:
        if _statcast_notes_cache["date"] == today and _statcast_notes_cache["text"] is not None:
            return {"notes": _statcast_notes_cache["text"]}

        report = await _get_statcast_report_cached()
        try:
            notes = ai_recap.generate_statcast_notes(report)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        _statcast_notes_cache["date"] = today
        _statcast_notes_cache["text"] = notes
        return {"notes": notes}


@app.get("/api/team/on-this-day")
async def team_on_this_day():
    # Cached daily: finding a candidate game means checking every year of
    # franchise history for today's month/day (~125 small requests), and
    # the blurb itself is a paid AI call — neither should re-run per visit.
    today = player_highlight.eastern_today()
    async with _on_this_day_lock:
        if _on_this_day_cache["date"] == today.isoformat() and _on_this_day_cache["data"] is not None:
            return _on_this_day_cache["data"]

        game = await on_this_day.get_on_this_day(today=today)
        if game is None:
            result = {"game": None}
        else:
            try:
                blurb = ai_recap.generate_on_this_day_blurb(game)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            result = {"game": {**game, "blurb": blurb}}

        _on_this_day_cache["date"] = today.isoformat()
        _on_this_day_cache["data"] = result
        return result


@app.get("/api/team/last-game-recap")
async def team_last_game_recap():
    # Cached by the actual completed game's gamePk, not calendar date: on an
    # off-day there's no new "yesterday's game" to speak of, so this should
    # just keep serving whatever the last real game was rather than trying
    # (and failing) to refresh once a day.
    data = await game_recap.get_last_game_recap_data()
    if data is None:
        return {"game": None}

    game_pk = data["game_pk"]
    async with _game_recap_lock:
        cached = _game_recap_cache["data"]
        if _game_recap_cache["game_pk"] == game_pk and cached is not None:
            return cached

        try:
            narrative = ai_recap.generate_game_recap(data)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        result = {"game": {**data, "narrative": narrative}}
        _game_recap_cache["game_pk"] = game_pk
        _game_recap_cache["data"] = result
        return result


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
