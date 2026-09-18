# The Fenway Almanac — Project Summary

**Live site:** https://fenway-form-finder.onrender.com
**Repo:** github.com/mikeenos14-tech/RedSox-Trends

## What it is

A full-stack, AI-powered analytics dashboard for the Boston Red Sox. It pulls
real, live season data from the free public MLB Stats API and Baseball
Savant, computes trend/form metrics on top of it, and uses the Claude API to
turn those numbers into natural-language "beat writer" style analysis. Built
as a "vibe coding" portfolio project — a cool, real output for friends and
family, and a way to build hands-on experience directing an AI coding
assistant through a genuinely large, multi-week build.

The project started as "Fenway Form Finder," was briefly "Stat Sox," and
settled on **The Fenway Almanac**.

## Why it exists

Demonstrates the same pattern used in production AI features: pull real
structured data → derive meaningful signal from it → ground an LLM prompt in
that data → generate readable output. Every AI-written section is explicitly
labeled "✨ AI-written" in the UI and is grounded in real fetched data, not
free-floating model knowledge — an intentional design choice to avoid
hallucinated stats.

## Stack

- **Backend:** Python, FastAPI, httpx (async MLB Stats API + Baseball Savant client)
- **AI:** Anthropic Claude API for all generated recaps/notes
- **Frontend:** Vanilla HTML/CSS/JS across 4 pages, no build step, no framework
- **Charts:** Chart.js (win probability line chart)
- **Data sources:** MLB Stats API (`statsapi.mlb.com`, free/no key) and
  Baseball Savant (`baseballsavant.mlb.com`, scraped — no official API exists)
- **Hosting:** Render (free tier), auto-deploys from `main` on every push

## Site structure (4 pages)

**Home** (`index.html`) — the daily-driver view:
- Live game ticker (polls every 15s during a live game — score, count, outs,
  baserunners on an SVG diamond, current matchup)
- Hero AI headline banner
- AL East standings + Wild Card race tables
- Previous Game Recap (box score + AI narrative + win-probability chart)
- Upcoming Schedule (next 10 games, division games flagged)
- Season Series Tracker (every opponent faced)
- Bullpen Availability (heuristic rest/fatigue tracker)

**League** (`league.html`) — big-picture context:
- AI Trend Recap
- Where Boston Ranks (of 30 MLB teams, stat benchmarks)
- Front Office Analysis (AI briefing)
- Headlines (last 3 days, with AI summary)

**Players** (`players.html`) — the deepest section, for die-hard fans:
- Player Hot/Cold Tracker — season vs. last-15-days, heat-mapped vs. league
  average, **sortable by clicking any column header**
- Statcast Scouting Report — Red Sox hitters/pitchers percentile profiles vs.
  Baseball Savant data, flagship League Leaders grid, plus a **"explore
  another leaderboard" picker** covering all 11 signature Statcast metrics
- **Player Comparison Tool** — search any 2026-qualified MLB hitter or
  pitcher (not just Red Sox) and get a head-to-head "tale of the tape"
  diverging-bar-chart comparison of their Statcast percentiles
- Player Highlight — one new Red Sox player featured daily (rotates at
  Eastern midnight), with AI-written bio

**Games** (`games.html`):
- Last 15 Games log
- On This Day (in Red Sox history, historical box score + AI blurb)

## Architecture notes worth remembering

- **Caching strategy, two patterns:**
  - `_cached_by_hash` — re-runs an AI generation only when the underlying
    data actually changed (avoids paying for a re-worded rehash of the same
    facts on every click)
  - `_cached_for` — time-boxed TTL (30 min) for heavy free-API fetches that
    don't need AI (e.g. full-season game log, roster-wide hot/cold report)
  - Statcast/league data additionally uses a same-day cache keyed on Eastern
    date, shared across the team report, player search, and player
    comparison endpoints so Baseball Savant only gets scraped once per day
    regardless of which feature is hit first
- **Timezone correctness:** `player_highlight.eastern_today()` is the one
  true "what day is it" helper. A real bug was caught and fixed where
  `bullpen.py` had been using the server's raw UTC clock instead, which
  would misjudge pitcher rest windows around midnight.
- **Live ticker data model gotcha:** baserunners live at
  `liveData.plays.currentPlay.matchup.postOnFirst/Second/Third`, not on
  `linescore.offense` (batter/on-deck only) or `linescore.defense.first/...`
  (a field-name collision — those are defensive *positions*, not runners).
- **No official Savant API** — the app hits the same JSON/CSV export
  endpoints Savant's own pages use client-side, with a browser-like
  User-Agent (the same approach the community `pybaseball` library takes).
- Baseball Savant IDs are strings, MLB Stats API IDs are ints for the same
  players — every cross-reference converts explicitly to avoid silent
  mismatches.
- **No MCP servers in the deployed app itself** — it's direct httpx +
  Anthropic SDK calls throughout. MCP (browser automation) was only used by
  the Claude Code session itself, for testing/screenshots during the build.

## Notable design decisions

- Every AI section is clearly badged so a reader always knows what's
  computed vs. generated
- Mobile-first responsive rules throughout (wrap instead of horizontal
  scroll was an explicit, repeated user preference)
- Statcast bar colors and the comparison tool's "Player A" blue were
  deliberately kept theme-aware (light/dark) rather than hardcoded, after an
  early contrast bug where a fixed navy was unreadable in dark mode
- Hosted on Render's free tier, which spins down after ~15 min idle — a
  known tradeoff, not yet resolved (options discussed: upgrade to a paid
  Render tier, or a periodic keep-warm ping)

## How this got built

Built incrementally over ~44 commits in one continuous "vibe coding" session
with Claude Code, roughly in this order: core dashboard + AI recap → visual
redesign and 4-page split → standings/wild-card/bullpen/win-probability →
Statcast scouting report → player highlight with real draft data → headlines
+ front-office analysis → player-level hot/cold tracker → branding passes
("Stat Sox" → "The Fenway Almanac") → live game ticker with a custom SVG
diamond → sortable tables, a leaderboard explorer, and the Statcast player
comparison tool.

## Possible next steps

- A companion site for another team (Patriots was discussed) — recommended
  as a *separate* project/chat rather than folded into this one
- Resolve the free-tier cold-start issue (paid tier vs. keep-warm ping)
- Scheduled daily digest email (originally on the README roadmap, not yet built)
