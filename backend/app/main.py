from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import ai_recap, league_context, mlb_client, news, player_stats, trends

app = FastAPI(title="Red Sox Season Trends")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


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

    try:
        notes = ai_recap.generate_player_notes(report)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"notes": notes}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
