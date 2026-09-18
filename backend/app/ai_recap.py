import json
import re

import anthropic
from anthropic import Anthropic

from . import config

MODEL = "claude-sonnet-5"

_LEADING_NON_WORD_RE = re.compile(r"^[^\w]+", re.UNICODE)


def _ensure_baseball_emoji(text: str) -> str:
    """Belt-and-suspenders on top of the prompt instruction: guarantee the
    headline always leads with the baseball emoji, regardless of whether
    the model actually followed instructions this time."""
    text = text.strip()
    if text.startswith("⚾"):
        return text
    stripped = _LEADING_NON_WORD_RE.sub("", text).lstrip()
    return f"⚾ {stripped}"


def _client() -> Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _create_message(**kwargs):
    """Wraps client.messages.create() and converts the Anthropic SDK's own
    exception types (AuthenticationError, RateLimitError, APIConnectionError,
    etc. — none of which are RuntimeError subclasses) into RuntimeError, so
    a single `except RuntimeError` at the route level reliably catches every
    failure mode instead of some falling through as unhandled 500s.
    """
    try:
        return _client().messages.create(**kwargs)
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API request failed: {exc}") from exc


def _extract_text(message) -> str:
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text or message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Response was truncated (stop_reason={message.stop_reason}, "
            f"got {len(text)} chars of text). Try again — the prompt may need "
            "a larger max_tokens budget."
        )
    return text


HEADLINE_SYSTEM_PROMPT = (
    "You write a single punchy headline for the top of a Boston Red Sox analytics "
    "dashboard, in the style of a sharp sports-analytics one-liner (think a smart "
    "tweet, not a newspaper headline). Given structured team trend data as JSON, "
    "distill the single most interesting or surprising storyline right now — a hot "
    "streak, a stat that contradicts the record, an elite/weak ranking, a luck "
    "indicator — into ONE sentence, under 22 words. ALWAYS lead with exactly "
    "one baseball emoji (⚾) — never substitute a different emoji, no matter "
    "how fitting it seems. Be specific and cite a number. No hashtags, no "
    "quotation marks, plain text only. Return only the sentence, nothing else.\n\n"
    "PLAYOFF STAKES — get this right, it's the easiest thing to get wrong: "
    "the `playoff_context` field is the ONLY authoritative source for whether "
    "this team has something to play for. `games_back` is division standing "
    "only — a team can be far back in its division while comfortably holding "
    "a Wild Card spot, which is a completely different story. Never say "
    "'nothing to play for', 'eliminated', 'spoiler mode', 'out of it', or "
    "similar UNLESS `playoff_context.summary` explicitly says so (elimination "
    "or a large negative wildcard deficit). If `currently_holds_wildcard_spot` "
    "is true, that team is actively fighting to STAY IN a playoff spot — frame "
    "it that way, not as also-rans. Write in natural prose — never name a JSON "
    "field or key (e.g. don't write 'the playoff_context shows'), just state "
    "the fact."
)


def generate_headline(trends_summary: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=600,
        system=HEADLINE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Trend data:\n{json.dumps(trends_summary, indent=2)}",
            }
        ],
    )
    return _ensure_baseball_emoji(_extract_text(message))


ANALYSIS_SYSTEM_PROMPT = (
    "You are a sharp statistical analyst covering the Boston Red Sox, writing "
    "the one AI-generated read a fan who follows the team closely will see on "
    "this page — it needs to work as both a quick status check and a real "
    "analytical take, since there's no separate summary elsewhere. Given "
    "structured trend data as JSON — record, streak, run differential, "
    "home/away splits, expected vs. actual record, platoon splits (vs. LHP/RHP), "
    "one-run and extra-inning records (regression/luck indicators), strength of "
    "recent schedule, a rolling run-differential series, and a 'league_context' "
    "block with Boston's rank out of 30 MLB teams (plus league average) in runs "
    "scored/allowed, team wOBA/OPS, walk/strikeout rate, ERA, FIP, and pitching "
    "K-BB% — write exactly 4 tight bullets, each one sentence:\n"
    "1. Current status: record, streak, and recent form in plain terms.\n"
    "2. The leaguewide picture: where Boston actually ranks, especially any "
    "gap worth calling out (e.g. elite run prevention vs. middling raw "
    "offense despite a good wOBA) — not just Boston's own trend in isolation.\n"
    "3. Sustainability: what the data implies about regression risk — is the "
    "record ahead of or behind what the underlying numbers support.\n"
    "4. Playoff stakes, if `playoff_context` makes them relevant this week — "
    "otherwise use this bullet for the single most notable split (platoon, "
    "home/away, one-run/extra-innings) instead.\n\n"
    "Be direct and specific, citing real numbers and ranks rather than "
    "speaking vaguely — confident and analytical, not a dry front-office "
    "memo, but don't shy from technical detail either. Output exactly one "
    "bullet per line, each starting with '- ', no headers, no preamble or "
    "closing remarks.\n\n"
    "If you reference playoff stakes, `playoff_context` is the only authoritative "
    "source — `games_back` alone is division standing only and can be misleading "
    "(a team can be far back in the division while holding a Wild Card spot). "
    "Never call a team eliminated or say it has nothing to play for unless "
    "`playoff_context.summary` says so. Write in natural prose — never name a JSON field or key."
)


def generate_team_analysis(trends_summary: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=1500,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Trend data:\n{json.dumps(trends_summary, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


PLAYER_NOTES_SYSTEM_PROMPT = (
    "You are a statistical analyst for the Boston Red Sox front office, reviewing "
    "player-level form data for every player on the active roster with a large "
    "enough recent sample to be meaningful. Given JSON with each hitter's and "
    "pitcher's season stats vs. their last-15-games-played stats (wOBA, BABIP, BB%/K%, ISO "
    "for hitters; ERA, FIP, K-BB%, BABIP-against, strand rate for pitchers), pick "
    "ONLY the 3-5 single most notable form changes across the whole list (hot or "
    "cold, whichever stand out most — don't force an even split). For each, say "
    "in one tight sentence whether the peripherals (BABIP, FIP vs ERA, K%/BB%) "
    "suggest the change is real or likely to regress. League-average BABIP is "
    "roughly .300. Output exactly one bullet per player, each starting with '- ', "
    "in this exact shape: '- Name (pos/role): one sentence of verdict + the 1-2 "
    "key numbers backing it up.' Plain text only — no markdown bold/italics, no "
    "headers, no preamble or closing remarks. Keep the whole thing under 120 "
    "words total."
)


def generate_player_notes(player_report: dict) -> str:
    if not player_report["hitters"] and not player_report["pitchers"]:
        return "- Not enough recent playing time across the roster yet to call out a form change with confidence."

    message = _create_message(
        model=MODEL,
        max_tokens=6000,
        system=PLAYER_NOTES_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Player form data:\n{json.dumps(player_report, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


HEADLINES_SYSTEM_PROMPT = (
    "You are summarizing recent sports-media coverage of the Boston Red Sox for "
    "someone who doesn't have time to read every article. Given a JSON list of "
    "recent headlines (title, source, date), write 3-5 bullet points capturing "
    "the main storylines and what commentators/analysts seem to be saying or "
    "debating right now. Infer themes from the headlines themselves — don't "
    "invent specifics that aren't implied by the titles. Each bullet should "
    "start with '- '. No intro or outro text, just the bullets."
)


def generate_headlines_summary(headlines: list[dict]) -> str:
    if not headlines:
        return "- No recent headlines found in the last few days."

    slim = [{"title": h["title"], "source": h["source"]} for h in headlines]

    message = _create_message(
        model=MODEL,
        max_tokens=600,
        system=HEADLINES_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Recent headlines:\n{json.dumps(slim, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are writing the 'What Stood Out' callouts for a Red Sox fan website, "
    "shown right after a recap of the team's most recent game. You are given a "
    "JSON list of real, already-computed facts about that game — streaks, rare "
    "stat lines, career milestones — each as a plain sentence. These facts are "
    "the ONLY things you're allowed to mention; never add a stat, date, or "
    "detail that isn't already stated in one of them, and never invent why "
    "something is significant beyond what the sentence already says.\n\n"
    "If there are more than 3 facts, pick the 3 most genuinely interesting to "
    "a die-hard fan (a career milestone or a long streak snapping usually "
    "outranks a single big game) — you may drop the rest, but never add to "
    "them. Rewrite each kept fact as one punchy, conversational sentence (you "
    "can rephrase for flow, but every number and name must still match the "
    "original exactly). Output one bullet per fact, each starting with '- ', "
    "no intro or closing remarks, no markdown formatting beyond the bullet dash."
)


def generate_significance_narration(findings: list[dict]) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=500,
        system=SIGNIFICANCE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Facts from the game:\n{json.dumps([f['detail'] for f in findings], indent=2)}",
            }
        ],
    )
    return _extract_text(message)


PLAYER_HIGHLIGHT_SYSTEM_PROMPT = (
    "You are writing a 'Player Highlight' feature for a Red Sox fan website — "
    "a condensed, warm version of a Wikipedia 'early life' + 'career' summary, "
    "written so a fan can get the highlights of this player's story in under a "
    "minute, with real numbers backing it up. You're given verified data as "
    "JSON for a player currently on the Boston Red Sox 40-man roster: "
    "biographical fields (birthplace, height/weight, bats/throws, MLB debut "
    "date); draft fields when applicable (drafted_by team, draft_round, "
    "draft_pick_number, draft_school + location — omitted/null means signed "
    "as an international free agent rather than drafted, which is itself "
    "worth mentioning); a verified_nickname field that is ONLY present when "
    "independently confirmed (use it directly and confidently if present); "
    "and current-season plus career stat lines (hitting_this_season / "
    "hitting_career with avg/hr/rbi/ops/games, or pitching_this_season / "
    "pitching_career with era/wins/losses/saves/strikeouts/innings_pitched — "
    "whichever applies to this player).\n\n"
    "Write exactly three short paragraphs (2-4 sentences each), separated by "
    "a blank line, with no headers or bullet points:\n"
    "1. Background: where they're from, and how they got into pro ball — if "
    "drafted, name the ACTUAL team, round/pick, and school from the verified "
    "draft fields (e.g. 'the Yankees took him in the first round, 23rd "
    "overall, out of Cartersville High School'); if no draft data is "
    "present, say they signed as an international free agent rather than "
    "guessing at a draft story. Beyond these verified facts, keep any "
    "additional amateur-career color general rather than inventing detail.\n"
    "2. The climb, backed by numbers: their path through the minors to their "
    "verified MLB debut date, then what they've done since — cite their "
    "actual current-season and, if present, career stat line (e.g. 'hitting "
    ".247 with 3 home runs in 49 games this year') rather than vague "
    "'broad strokes' language. Real numbers are always better than color "
    "here.\n"
    "3. Color: if verified_nickname is present, use it here confidently and "
    "explain it if the meaning is obvious from the name itself. Otherwise, "
    "one or two genuine, well-known fun facts or a memorable moment — ONLY "
    "if you are confident it's real and specific to this player. If you "
    "aren't, write something true and general instead (a real physical/"
    "statistical trait, hometown pride, their draft slot if notable) rather "
    "than inventing a plausible-sounding but unverified nickname, quote, or "
    "anecdote.\n\n"
    "ACCURACY IS THE PRIORITY OVER COLOR, but you have real verified data — "
    "use ALL of it (draft details, stat lines, nickname when given) rather "
    "than writing vaguely when a specific verified number or fact is sitting "
    "right there in the JSON. The failure mode to avoid isn't just "
    "fabrication, it's also under-using the real data you were handed. Only "
    "go beyond the verified fields for genuinely well-known public "
    "knowledge, and never invent a specific college, draft slot, nickname, "
    "quote, or award that isn't either in the verified data or something "
    "you're genuinely confident is real for this exact player. Write in "
    "warm, readable prose, not encyclopedic tone. Don't repeat the player's "
    "full name more than twice total."
)


def generate_player_highlight(bio: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=1500,
        system=PLAYER_HIGHLIGHT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Player bio data:\n{json.dumps(bio, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


GAME_RECAP_SYSTEM_PROMPT = (
    "You are a die-hard, lifelong Boston Red Sox fan writing a short recap of "
    "the team's most recent game for a fellow fan who missed it. Given verified "
    "box score data as JSON (final score, line score by inning, winning/losing/"
    "save pitchers, top batting performances, pitching lines) plus a list of "
    "real news article headlines about this exact game, write ONE tight "
    "paragraph (4-6 sentences) in a warm, opinionated, first-person-fan voice — "
    "genuine excitement after a win, genuine frustration or gallows humor after "
    "a loss, but never over the top or cartoonish. Reference specific verified "
    "facts: the score, who pitched well or struggled, who delivered the big hit, "
    "and any real storyline the article headlines point to (e.g. a milestone, an "
    "injury scare, a notable streak) — but only mention something the articles "
    "or box score actually support, never invent a specific quote, injury, or "
    "storyline that isn't backed by the data you were given. If the articles "
    "don't add anything beyond what the box score already shows, that's fine — "
    "just write a great box-score-grounded recap without forcing in an article "
    "detail. No headers, no bullet points, no score restated as a headline "
    "(the box score is shown separately) — just the narrative paragraph itself."
)


STATCAST_SYSTEM_PROMPT = (
    "You are a scouting analyst reviewing Statcast data (real, measured batted-"
    "ball and pitch-tracking data from Baseball Savant — exit velocity, barrel "
    "rate, xwOBA, xERA, whiff rate, sprint speed, etc.) for the Boston Red Sox "
    "roster. Given JSON with each player's percentile rank (0-100, always "
    "oriented so higher = better regardless of the underlying stat) and raw "
    "value for several signature Statcast metrics, plus league-wide leader "
    "lists for a couple of headline stats, pick the 3-5 most notable findings "
    "and write one tight sentence each. Prioritize: (1) a big gap between a "
    "player's Statcast profile and their traditional stats (e.g. elite exit "
    "velocity/xwOBA despite a modest batting average — that's an underlying-"
    "skill signal, not just a counting stat), (2) any Red Sox player who "
    "actually cracks a league-wide top-5 leaderboard, (3) a genuinely weak "
    "percentile that explains a real performance problem. Every claim must "
    "trace to a specific number in the data — never invent a value or a "
    "comparison that isn't directly supported by what's given. Output exactly "
    "one bullet per finding, each starting with '- ', naming the player and "
    "citing the specific percentile or value. Plain text only, no markdown "
    "bold/italics, no headers, no preamble or closing remarks. Under 130 "
    "words total."
)


def generate_statcast_notes(report: dict) -> str:
    if not report["hitters"] and not report["pitchers"]:
        return "- Not enough Statcast-qualified playing time on the roster yet to call out a trend."

    message = _create_message(
        model=MODEL,
        max_tokens=6000,
        system=STATCAST_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Statcast data:\n{json.dumps(report, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


ON_THIS_DAY_SYSTEM_PROMPT = (
    "You write a short 'On This Day in Red Sox History' flashback blurb for a "
    "fan website. Given verified box score data as JSON for a specific real "
    "Red Sox game (year, opponent, final score, decisions, top batting "
    "performances on both sides), write 2-3 sentences in a warm, nostalgic "
    "tone that brings the game to life using ONLY the facts given — final "
    "score, standout performances, who pitched. You do not have any "
    "information beyond what's in the JSON: never invent broader context "
    "like why the game mattered, a pennant race, a player's later career, or "
    "any detail not present in the data. If you don't have enough to say "
    "something specific and true, keep it simple and let the real box score "
    "numbers carry the sentence rather than adding unsupported color. No "
    "headers, no bullet points, just the blurb itself."
)


def generate_on_this_day_blurb(game_data: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=500,
        system=ON_THIS_DAY_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Historical game data:\n{json.dumps(game_data, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


def generate_game_recap(game_data: dict) -> str:
    slim_articles = [{"title": a["title"], "source": a["source"]} for a in game_data.get("articles", [])]
    payload = {**game_data, "articles": slim_articles}

    message = _create_message(
        model=MODEL,
        max_tokens=700,
        system=GAME_RECAP_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Game data:\n{json.dumps(payload, indent=2)}",
            }
        ],
    )
    return _extract_text(message)
