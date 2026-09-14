from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import ai_recap, mlb_client, news, trends

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


@app.get("/api/team/analysis")
async def team_analysis():
    summary = await _build_summary()

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


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
