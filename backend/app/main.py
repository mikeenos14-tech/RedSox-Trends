from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (
    adjusted,
    ai_recap,
    bullpen,
    cache,
    config,
    game_recap,
    http,
    league_context,
    live_game,
    mlb_client,
    news,
    on_this_day,
    player_highlight,
    player_profile,
    player_stats,
    season,
    season_review,
    significance,
    statcast,
    team_profile,
    trends,
    win_probability,
)

logger = logging.getLogger("uvicorn.error")

# Proactively (re)generate every AI output on a schedule instead of on a
# visitor's page load: a new recap is ready within ~10 minutes of a game
# going final, the daily highlight shortly after midnight, and analysis
# whenever its underlying data changes — nobody waits 10-18s on a cold
# cache. Each pass is cheap when nothing changed: in-memory and persisted
# caches (see ai_store) short-circuit before any Claude call. On by default
# on Railway; off locally unless WARM_AI_CACHE=1, so a dev server restart
# doesn't spend API credits.
WARM_INTERVAL_SECONDS = 600
WARM_ENABLED = os.getenv("WARM_AI_CACHE", "1" if os.getenv("RAILWAY_ENVIRONMENT") else "0") == "1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_warm_loop()) if WARM_ENABLED else None
    yield
    if task:
        task.cancel()
    await http.aclose_all()


app = FastAPI(title="The Fenway Almanac", lifespan=lifespan)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

# Every cache on the site is a cache.Memo; the key is the invalidation rule
# (see cache.py). Eastern "today" is the day boundary everywhere.
HEAVY_FETCH_CACHE_SECONDS = 1800  # 30 min: all-30-teams stats, roster game logs, etc.
HEADLINES_CACHE_SECONDS = 600  # news moves faster than season stats
UPCOMING_CACHE_SECONDS = 120  # probable starters change, but not minute to minute
LIVE_GAME_CACHE_SECONDS = 10  # shared across visitors; each miss pulls an ~800KB feed

_season_games = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_hot_cold = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_full_roster = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_all_team_stats = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_league_context = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_stat_benchmarks = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)
_headlines = cache.Memo(ttl=HEADLINES_CACHE_SECONDS)
_upcoming = cache.Memo(ttl=UPCOMING_CACHE_SECONDS)
_live = cache.Memo(ttl=LIVE_GAME_CACHE_SECONDS)
_league_data = cache.Memo()  # keyed by day: Savant recalculates once daily
_statcast_report = cache.Memo()  # keyed by day
_statcast_notes = cache.Memo()  # keyed by day
_highlight = cache.Memo()  # keyed by day: one featured player per day
_on_this_day = cache.Memo()  # keyed by day
_recap = cache.Memo()  # keyed by gamePk: a final game's facts never change
_win_prob = cache.Memo()  # keyed by gamePk
_significance = cache.Memo()  # keyed by gamePk; partial results not stored
_analysis = cache.Memo()  # keyed by input hash: Claude only when inputs change
_player_notes = cache.Memo()  # keyed by input hash
_season_review = cache.Memo(ttl=HEAVY_FETCH_CACHE_SECONDS)  # keyed by day
_team_profiles = cache.Memo(max_keys=64)  # keyed by (team id, day)
_player_profiles = cache.Memo(max_keys=128)  # keyed by (player id, day)


def _today() -> str:
    return config.eastern_today().isoformat()


def _as_503(compute):
    """Wrap an AI-generating coroutine so a Claude failure becomes a 503
    (and isn't cached)."""

    async def wrapped():
        try:
            return await compute()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return wrapped


async def _get_season_games_cached() -> list[dict]:
    # Upcoming Schedule and Season Series both need the full-season game
    # log. A full year's lookback, clamped to the season's own start date
    # inside get_recent_games — a fixed "last 200 days" silently dropped the
    # first games of the season once October ran long.
    return await _season_games.get(None, lambda: mlb_client.get_recent_games(days=366))


async def _get_player_hot_cold_cached() -> dict:
    return await _hot_cold.get(None, player_stats.get_player_hot_cold_report)


async def _get_full_roster_cached() -> dict:
    return await _full_roster.get(None, player_stats.get_full_roster_report)


async def _get_all_team_stats_cached() -> dict:
    # Shared by Where Boston Ranks and every team page: the all-30-teams
    # fetch is identical whichever team's ranks get computed from it.
    return await _all_team_stats.get(None, league_context.fetch_all_team_stats)


async def _get_headlines_cached() -> list[dict]:
    return await _headlines.get(None, news.get_recent_headlines)


@app.middleware("http")
async def resolve_season(request: Request, call_next):
    # Cheap no-op except on the first API request of each Eastern day, when
    # it re-checks MLB's calendar — this is what rolls the whole site over
    # to a new season on Opening Day with no code change or redeploy.
    if request.url.path.startswith("/api/"):
        await season.ensure_fresh()
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        # Static HTML/CSS/JS had no Cache-Control, so browsers applied
        # heuristic freshness and kept serving the previous deploy's
        # style.css/common.js for hours — new HTML with old JS/CSS.
        # "no-cache" means always revalidate: unchanged files cost a tiny
        # 304 via the ETag StaticFiles already sends; changed ones arrive
        # immediately after a deploy.
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full traceback server-side (visible in Railway's deploy logs)
    # but never expose exception internals to the client — file paths,
    # package versions, etc. shouldn't be handed to anyone who can trigger
    # an error on a public-facing app.
    logger.error("Unhandled exception on %s:\n%s", request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def _build_summary() -> dict:
    standings, games, win_pcts, postseason_games = await asyncio.gather(
        mlb_client.get_team_standings(),
        mlb_client.get_recent_games(),
        mlb_client.get_league_win_pcts(),
        mlb_client.get_postseason_games(),
    )
    summary = trends.build_trends_summary(standings, games, win_pcts)
    # Everything above is regular-season only by design (splits, streaks,
    # run differential); October lives in its own block so the two never
    # blend, and so the header and the AI analysis know the season phase.
    summary["postseason"] = trends.summarize_postseason(postseason_games, config.TEAM_ID)
    return summary


@app.get("/api/team/summary")
async def team_summary():
    return await _build_summary()


async def _park_factors() -> dict:
    """Savant park factors from the day-cached Savant pull. Empty on failure,
    and the park-adjusted stats are then omitted rather than shown
    unadjusted."""
    try:
        return (await _get_league_data_cached()).get("park_factors") or {}
    except Exception as exc:  # noqa: BLE001 — Savant is a scrape
        logger.warning("Park factors unavailable: %s", exc)
        return {}


async def _boston_league_context() -> dict:
    all_team_stats, parks = await asyncio.gather(_get_all_team_stats_cached(), _park_factors())
    return league_context.compute_league_context(config.TEAM_ID, all_team_stats, parks)


def _add_adjusted(report: dict, baselines: dict | None, pf: float) -> dict:
    """OPS+ / ERA- / FIP- onto roster-report season lines (a copy — the
    cached report stays untouched)."""
    if not baselines:
        return report
    out = {**report, "hitters": [], "pitchers": []}
    for h in report["hitters"]:
        s = h["season"]
        out["hitters"].append({**h, "season": {**s, "ops_plus": adjusted.ops_plus(s.get("obp"), s.get("slg"), baselines, pf)}})
    for p in report["pitchers"]:
        s = p["season"]
        out["pitchers"].append({**p, "season": {
            **s,
            "era_minus": adjusted.era_minus(s.get("era"), baselines, pf),
            "fip_minus": adjusted.fip_minus(s.get("fip"), baselines, pf),
        }})
    return out


async def _adjustment_inputs(team_id: int = config.TEAM_ID) -> tuple:
    all_team_stats, parks = await asyncio.gather(_get_all_team_stats_cached(), _park_factors())
    if not parks:
        return None, 1.0
    return adjusted.league_baselines(all_team_stats), adjusted.half_park_factor(team_id, parks)


@app.get("/api/team/league-context")
async def team_league_context():
    return await _league_context.get(None, _boston_league_context)


@app.get("/api/team/division-standings")
async def team_division_standings():
    return {"teams": await mlb_client.get_division_standings()}


@app.get("/api/team/stat-benchmarks")
async def team_stat_benchmarks():
    return await _stat_benchmarks.get(None, league_context.get_stat_benchmarks)


def _pitcher_line(person: dict) -> dict | None:
    stat = player_stats._first_split(person, "season", "pitching")
    if not stat:
        return None
    return {
        "era": stat.get("era"),
        "wins": stat.get("wins"),
        "losses": stat.get("losses"),
        "innings_pitched": stat.get("inningsPitched"),
        "strikeouts": stat.get("strikeOuts"),
        "whip": stat.get("whip"),
    }


@app.get("/api/team/upcoming-schedule")
async def team_upcoming_schedule():
    # Five MLB requests per build and it's on every Home load — probable
    # starters and records don't change minute to minute.
    return await _upcoming.get(None, _build_upcoming_schedule)


async def _build_upcoming_schedule():
    games, division_teams, season_games, league_records, postseason_games = await asyncio.gather(
        mlb_client.get_upcoming_games(),
        mlb_client.get_division_standings(),
        _get_season_games_cached(),
        mlb_client.get_league_records(),
        mlb_client.get_postseason_games(),
    )
    division_ids = {t["id"] for t in division_teams if not t["is_target"]}
    season_series = mlb_client.build_season_series(season_games)

    for g in games:
        if g["postseason"]:
            # In October the schedule's leagueRecord is the postseason
            # record (0-0 before Game 1), and "division game" / "season
            # series" framing no longer applies — show the opponent's real
            # regular-season record instead.
            g["is_division_game"] = False
            g["season_series"] = None
            g["opponent_record"] = league_records.get(g["opponent_id"]) or g["opponent_record"]
        else:
            g["is_division_game"] = g["opponent_id"] in division_ids
            series = season_series.get(g["opponent_id"])
            g["season_series"] = {"wins": series["wins"], "losses": series["losses"]} if series else None

    # Season lines for every listed probable starter, in one request — the
    # next-game card shows the matchup, not just two names.
    pitcher_ids = sorted(
        {pid for g in games for pid in (g["us_probable_pitcher_id"], g["opponent_probable_pitcher_id"]) if pid}
    )
    lines: dict = {}
    if pitcher_ids:
        try:
            people = await player_stats._get_people_with_stats(pitcher_ids)
            lines = {p["id"]: _pitcher_line(p) for p in people}
        except httpx.HTTPError as exc:
            logger.warning("Probable-pitcher stats unavailable: %s", exc)
    for g in games:
        g["us_probable_pitcher_line"] = lines.get(g["us_probable_pitcher_id"])
        g["opponent_probable_pitcher_line"] = lines.get(g["opponent_probable_pitcher_id"])

    pcts = [float(g["opponent_record"]["pct"]) for g in games if g["opponent_record"].get("pct")]
    home_count = sum(1 for g in games if g["home_or_away"] == "home")
    postseason = trends.summarize_postseason(postseason_games, config.TEAM_ID)
    if postseason:
        postseason = {k: v for k, v in postseason.items() if k != "games"}

    return {
        "games": games,
        "team_record": league_records.get(config.TEAM_ID),
        "postseason": postseason,
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


@app.get("/api/team/profile")
async def team_profile_endpoint(id: int):
    # Day-cached per team, same rationale as the player-profile cache — a
    # team's record/rank/top-performers don't need recomputing on every
    # single visit, only once the calendar day actually turns over.
    return await _team_profiles.get((id, _today()), lambda: _build_team_profile(id))


async def _build_team_profile(id: int) -> dict:
    all_team_stats, parks = await asyncio.gather(_get_all_team_stats_cached(), _park_factors())
    try:
        profile = await team_profile.get_team_profile(id, all_team_stats, parks)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    season_games, upcoming = await asyncio.gather(_get_season_games_cached(), mlb_client.get_upcoming_games())
    series = mlb_client.build_season_series(season_games).get(id)
    profile["season_series_vs_us"] = {"wins": series["wins"], "losses": series["losses"]} if series else None
    next_game = next((g for g in upcoming if g["opponent_id"] == id), None)
    profile["next_matchup"] = (
        {
            "date": next_game["date"],
            "home_or_away": next_game["home_or_away"],
            "us_probable_pitcher": next_game["us_probable_pitcher"],
            "us_probable_pitcher_id": next_game["us_probable_pitcher_id"],
            "postseason": next_game["postseason"],
        }
        if next_game
        else None
    )
    return profile


@app.get("/api/team/win-probability")
async def team_win_probability():
    # The play-by-play fetch here is the heaviest single request on the
    # site (~1MB) and only actually changes when a new game completes, so
    # it's cached by gamePk exactly like Previous Game Recap — cheap to
    # check (just the schedule lookup), expensive to skip checking.
    game = await game_recap.get_last_completed_game()
    if game is None:
        return {"game": None}


    async def compute():
        return {"game": await win_probability.get_last_game_win_probability(game=game)}

    return await _win_prob.get(game["gamePk"], compute)


@app.get("/api/team/last-game-significance")
async def team_last_game_significance():
    # Cached forever by gamePk, same as the win-probability/recap endpoints —
    # a completed game's real facts never change, so there's nothing to
    # recompute on a later request for the same game. The one AI call inside
    # (narration only, never invention) only fires on a genuine cache miss.
    #
    # The cache is checked against the last game's gamePk (one cheap
    # schedule lookup) *before* running any checks — the full check suite is
    # dozens of MLB requests and must not run on every Home page view.
    game = await game_recap.get_last_completed_game()
    if game is None:
        return {"game_pk": None, "narration": None}

    async def compute():
        report = await significance.get_game_significance(game=game)
        result = {"game_pk": report["game_pk"], "date": report["date"], "narration": None, "complete": report["complete"]}
        # Incomplete = some game logs hadn't caught up yet (MLB lags a few
        # minutes after Final): show nothing, don't pay for narration of a
        # partial list, and don't cache — a later request gets the full answer.
        if report["complete"] and report["findings"]:
            result["narration"] = await _as_503(lambda: ai_recap.generate_significance_narration(report["findings"]))()
        return result

    result = await _significance.get(game["gamePk"], compute, store_if=lambda r: r["complete"])
    return {k: v for k, v in result.items() if k != "complete"}


async def _fetch_live_game() -> dict:
    return {"game": await live_game.get_live_game()}


@app.get("/api/team/live-game")
async def team_live_game():
    # "What's true right now," polled every ~15s by open Home pages and every
    # minute by the nav indicator on every page. Shared for 10s across all
    # visitors so cost doesn't scale with traffic: each miss pulls MLB's
    # full live feed (~800KB).
    return await _live.get(None, _fetch_live_game)


@app.get("/api/team/analysis")
async def team_analysis():
    # Merged with what used to be the separate "AI Trend Recap" — both took
    # the same trend data and produced overlapping paragraphs (team status +
    # analytical read), just in two different voices. One richer paragraph
    # serves both purposes without repeating itself.
    summary = await _build_summary()
    lg_ctx = await _league_context.get(None, _boston_league_context)
    summary["league_context"] = {k: v for k, v in lg_ctx.items() if k != "run_diff_league_chart"}
    # Savant's expected stats, so any "luck" claim is grounded in xwOBA
    # rather than inferred from runs vs. wOBA (the analysis once called an
    # offense that was *outperforming* its xwOBA unlucky).
    try:
        profile = statcast.build_team_profile(await _get_league_data_cached())
        summary["statcast_team"] = {
            side: {b["label"]: {"value": b["display"], "rank": b["rank"], "of": b["of"]} for b in profile[side].values()}
            for side in ("hitting", "pitching")
        } | {"hitting_luck": profile["hitting_luck"], "pitching_luck": profile["pitching_luck"]}
    except Exception as exc:  # noqa: BLE001 — Savant is a scrape; analysis still works without it
        logger.warning("Statcast team profile unavailable for analysis: %s", exc)

    # Keyed by the inputs' hash: Claude runs only when something changed.
    analysis = await _analysis.get(cache.stable_hash(summary), _as_503(lambda: ai_recap.generate_team_analysis(summary)))
    return {"analysis": analysis}


@app.get("/api/team/season-review")
async def team_season_review():
    # The offseason Home card. The cheap season-over check runs first; the
    # heavier inputs (league ranks, park-adjusted roster) only when it's
    # actually shown.
    async def compute():
        over, standings, postseason_games = await season_review.check()
        if not over:
            return {"season_over": False}
        ctx, roster, (baselines, pf) = await asyncio.gather(
            _league_context.get(None, _boston_league_context), _get_full_roster_cached(), _adjustment_inputs()
        )
        return await season_review.build(standings, postseason_games, ctx, _add_adjusted(roster, baselines, pf))

    return await _season_review.get(_today(), compute)


@app.get("/api/team/headlines")
async def team_headlines():
    headlines = await _get_headlines_cached()
    return {"headlines": headlines}



@app.get("/api/players/hot-cold")
async def players_hot_cold():
    return await _get_player_hot_cold_cached()


@app.get("/api/players/full-roster")
async def players_full_roster():
    report, (baselines, pf) = await asyncio.gather(_get_full_roster_cached(), _adjustment_inputs())
    return _add_adjusted(report, baselines, pf)


@app.get("/api/players/notes")
async def players_notes():
    report = await _get_player_hot_cold_cached()
    slim_report = player_stats.slim_for_ai(report)

    notes = await _player_notes.get(
        cache.stable_hash(slim_report), _as_503(lambda: ai_recap.generate_player_notes(slim_report))
    )
    return {"notes": notes}


@app.get("/api/players/highlight")
async def players_highlight():
    # Cached for the calendar day (Eastern time — see
    # player_highlight.eastern_today for why): the whole point is one
    # player featured per day for everyone, not a fresh AI-written bio
    # (and roster fetch) on every visit.
    async def compute():
        bio = await player_highlight.get_daily_highlight()
        narrative = await _as_503(lambda: ai_recap.generate_player_highlight(bio))()
        return {**bio, "narrative": narrative}

    return await _highlight.get(_today(), compute)


@app.get("/api/players/profile")
async def players_profile(id: int):
    # Day-cached per player (Eastern) — a player's page doesn't need to
    # recompute career/game-log/Statcast data on every single visit, only
    # once the calendar day actually turns over.
    return await _player_profiles.get((id, _today()), lambda: _build_player_profile(id))


async def _build_player_profile(id: int) -> dict:
    profile = await player_profile.get_player_profile(id, get_league_data=_get_league_data_cached)
    if profile is None:
        raise HTTPException(status_code=404, detail="Player not found on the current 40-man roster")
    baselines, pf = await _adjustment_inputs()
    if baselines:
        hit, pit = profile.get("hitting_this_season"), profile.get("pitching_this_season")
        if hit:
            hit["ops_plus"] = adjusted.ops_plus(hit.get("obp"), hit.get("slg"), baselines, pf)
        if pit:
            pit["era_minus"] = adjusted.era_minus(pit.get("era"), baselines, pf)
    return profile


async def _get_league_data_cached() -> dict:
    # Savant recalculates percentiles once daily after games are logged, so
    # a same-day cache avoids re-scraping several leaderboard pages (no
    # official API, so being a light touch matters) on every page view —
    # shared by the team report, player search, and player comparison so
    # only the first of those hit today pays the Savant round-trip.
    return await _league_data.get(_today(), statcast.fetch_league_data)


async def _get_statcast_report_cached() -> dict:
    async def compute():
        return await statcast.get_statcast_report(await _get_league_data_cached())

    return await _statcast_report.get(_today(), compute)


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
    async def compute():
        report = await _get_statcast_report_cached()
        return await _as_503(lambda: ai_recap.generate_statcast_notes(report))()

    return {"notes": await _statcast_notes.get(_today(), compute)}


@app.get("/api/team/on-this-day")
async def team_on_this_day():
    # Cached daily: finding a candidate game means checking every year of
    # franchise history for today's month/day (~125 small requests) — no
    # AI cost here, this is a plain box-score lookup, but the search itself
    # still shouldn't re-run per visit.
    today = config.eastern_today()

    async def compute():
        return {"game": await on_this_day.get_on_this_day(today=today)}

    return await _on_this_day.get(today.isoformat(), compute)


@app.get("/api/team/last-game-recap")
async def team_last_game_recap():
    # Cached by the actual completed game's gamePk, not calendar date: on an
    # off-day there's no new "yesterday's game" to speak of, so this should
    # just keep serving whatever the last real game was rather than trying
    # (and failing) to refresh once a day.
    #
    # Checked by gamePk first (one schedule lookup) so a cache hit skips the
    # box score and Google News fetches entirely.
    game = await game_recap.get_last_completed_game()
    if game is None:
        return {"game": None}

    async def compute():
        data = await game_recap.get_last_game_recap_data(game=game)
        narrative = await _as_503(lambda: ai_recap.generate_game_recap(data))()
        return {"game": {**data, "narrative": narrative}}

    return await _recap.get(game["gamePk"], compute)


async def warm_ai_outputs() -> None:
    """One pass over every AI-backed endpoint, oldest-news-first. Each call
    goes through the endpoint's own caching, so only genuinely new inputs
    reach Claude. A failure in one never blocks the rest."""
    await season.ensure_fresh()
    for name, endpoint in (
        ("last-game recap", team_last_game_recap),
        ("what stood out", team_last_game_significance),
        ("team analysis", team_analysis),
        ("player notes", players_notes),
        ("player highlight", players_highlight),
        ("statcast notes", players_statcast_notes),
    ):
        started = time.monotonic()
        try:
            await endpoint()
        except Exception as exc:  # noqa: BLE001 — log and move on; next pass retries
            logger.warning("AI warm-up: %s failed: %s", name, exc)
        else:
            elapsed = time.monotonic() - started
            if elapsed > 2:
                logger.info("AI warm-up: %s generated in %.1fs", name, elapsed)


async def _warm_loop() -> None:
    while True:
        await warm_ai_outputs()
        await asyncio.sleep(WARM_INTERVAL_SECONDS)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
