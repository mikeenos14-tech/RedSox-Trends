import logging
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai_recap, league_context, mlb_client, news, player_stats, trends

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Stat Sox")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


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


@app.get("/api/team/recap")
async def team_recap():
    summary = await _build_summary()

    try:
        recap = ai_recap.generate_recap(summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"recap": recap}


@app.get("/api/team/league-context")
async def team_league_context():
    return await league_context.get_league_context()


@app.get("/api/team/division-standings")
async def team_division_standings():
    return {"teams": await mlb_client.get_division_standings()}


@app.get("/api/team/stat-benchmarks")
async def team_stat_benchmarks():
    return await league_context.get_stat_benchmarks()


@app.get("/api/team/upcoming-schedule")
async def team_upcoming_schedule():
    games = await mlb_client.get_upcoming_games()
    division_teams = await mlb_client.get_division_standings()
    division_ids = {t["id"] for t in division_teams if not t["is_target"]}

    for g in games:
        g["is_division_game"] = g["opponent_id"] in division_ids

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


@app.get("/api/team/hero-headline")
async def team_hero_headline():
    summary = await _build_summary()

    try:
        headline = ai_recap.generate_headline(summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"headline": headline}


@app.get("/api/team/analysis")
async def team_analysis():
    summary = await _build_summary()
    lg_ctx = await league_context.get_league_context()
    summary["league_context"] = {k: v for k, v in lg_ctx.items() if k != "run_diff_league_chart"}

    try:
        analysis = ai_recap.generate_front_office_analysis(summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"analysis": analysis, "data": summary["analysis"]}


@app.get("/api/team/headlines")
async def team_headlines():
    headlines = await news.get_recent_headlines()
    return {"headlines": headlines}


@app.get("/api/team/headlines/summary")
async def team_headlines_summary():
    headlines = await news.get_recent_headlines()

    try:
        summary = ai_recap.generate_headlines_summary(headlines)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"summary": summary}


@app.get("/api/players/hot-cold")
async def players_hot_cold():
    return await player_stats.get_player_hot_cold_report()


@app.get("/api/players/notes")
async def players_notes():
    report = await player_stats.get_player_hot_cold_report()
    slim_report = player_stats.slim_for_ai(report)

    try:
        notes = ai_recap.generate_player_notes(slim_report)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"notes": notes}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
