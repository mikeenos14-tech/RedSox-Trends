# The Fenway Almanac

An AI-powered analytics dashboard for the Boston Red Sox. It pulls live season
data from the public MLB Stats API, computes form/trend metrics (hot/cold
streaks, run differential, home/away splits, expected vs. actual record), and
uses the Claude API to generate a natural-language "beat writer" style recap
of what the numbers mean.

## Why this exists

Built as a portfolio project to demonstrate practical, applied AI engineering:
pulling real structured data, deriving meaningful trends from it, and using an
LLM to turn those numbers into readable analysis — the same pattern used in
production AI features (data pipeline → grounded prompt → generated summary).

## Stack

- **Backend:** Python, FastAPI, httpx (async MLB Stats API client)
- **AI:** Anthropic Claude API for recap generation
- **Frontend:** Vanilla HTML/CSS/JS dashboard (no build step)
- **Data source:** [MLB Stats API](https://statsapi.mlb.com) (free, public, no key required)

## Setup

1. Install dependencies:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Add your Anthropic API key:
   ```bash
   cp .env.example .env
   # then edit .env and paste your key from console.anthropic.com
   ```

3. Run the server:
   ```bash
   uvicorn app.main:app --reload
   ```

4. Open http://localhost:8000 in your browser.

## Project structure

```
backend/
  app/
    config.py       # env vars / settings
    mlb_client.py    # MLB Stats API client
    trends.py        # derives trend metrics from raw MLB data
    ai_recap.py      # builds prompt + calls Claude API
    main.py          # FastAPI app, API routes, serves frontend
  requirements.txt
  .env.example
frontend/
  index.html
  style.css
  app.js
```

## Roadmap

- [x] Red Sox season trends + AI recap (v1)
- [ ] Extend to Patriots (NFL) and Bruins (NHL)
- [ ] Scheduled daily digest email
- [ ] Deploy publicly (Render/Railway + static frontend)
