from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import ai_recap, mlb_client, trends

app = FastAPI(title="Red Sox Season Trends")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/api/team/summary")
async def team_summary():
    standings = await mlb_client.get_team_standings()
    games = await mlb_client.get_recent_games()
    return trends.build_trends_summary(standings, games)


@app.get("/api/team/recap")
async def team_recap():
    standings = await mlb_client.get_team_standings()
    games = await mlb_client.get_recent_games()
    summary = trends.build_trends_summary(standings, games)

    try:
        recap = ai_recap.generate_recap(summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"recap": recap}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
