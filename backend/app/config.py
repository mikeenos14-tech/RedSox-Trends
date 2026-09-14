import os
from pathlib import Path

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
