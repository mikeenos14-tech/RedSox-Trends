import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# override=True: this app's own .env must win over any ANTHROPIC_API_KEY
# already present in the parent process's environment (e.g. from the
# terminal/IDE that launched it), since that's almost never the key
# intended for this app.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

TEAM_ID = 111  # Boston Red Sox
LEAGUE_ID = 103  # American League
SEASON = 2026

# MLB Stats API gameType codes. Regular-season stats (standings splits,
# season series, hot/cold, trends) must stay "R"-only, but anything that
# answers "what's the next/last/live game" has to see October too —
# otherwise the site goes dark the moment the team clinches.
REGULAR_SEASON_GAME_TYPE = "R"
POSTSEASON_GAME_TYPES = ("F", "D", "L", "W")  # Wild Card, Division Series, LCS, World Series
ALL_GAME_TYPES = ",".join((REGULAR_SEASON_GAME_TYPE, *POSTSEASON_GAME_TYPES))

# The server (Render) runs on UTC, but "today" for anything day-boundary
# sensitive (the daily Player Highlight rotation/cache) should mean
# midnight for the site's actual audience, not midnight UTC — which would
# otherwise flip over around 8pm ET the evening before. ZoneInfo handles
# the EST/EDT switch automatically, unlike a fixed UTC offset.
EASTERN_TZ = ZoneInfo("America/New_York")
