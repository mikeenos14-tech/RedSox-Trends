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


SYSTEM_PROMPT = (
    "You are a sharp, knowledgeable beat writer covering the Boston Red Sox. "
    "Given structured season-trend data as JSON, write a short recap (4-6 sentences) "
    "in a confident, analytical voice for a fan who follows the team closely. "
    "Reference specific numbers from the data (record, streak, run differential, "
    "home/away splits, expected vs. actual record) rather than speaking vaguely. "
    "Call out whether the underlying trends (run differential, expected record) "
    "support or contradict the team's recent results. No headers, no bullet points, "
    "just a tight paragraph.\n\n"
    "If you reference playoff stakes, `playoff_context` is the only authoritative "
    "source — `games_back` alone is division standing only and can be misleading "
    "(a team can be far back in the division while holding a Wild Card spot). "
    "Never call a team eliminated or say it has nothing to play for unless "
    "`playoff_context.summary` says so. Write in natural prose — never name a JSON field or key."
)


def generate_recap(trends_summary: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Season trend data:\n{json.dumps(trends_summary, indent=2)}",
            }
        ],
    )
    return _extract_text(message)


ANALYSIS_SYSTEM_PROMPT = (
    "You are a front-office statistical analyst for the Boston Red Sox, briefing "
    "the baseball operations department. Given structured trend data as JSON — "
    "including platoon splits (vs. LHP/RHP), one-run and extra-inning records "
    "(regression/luck indicators), strength of recent schedule, a rolling "
    "run-differential series, and a 'league_context' block with Boston's rank "
    "out of 30 MLB teams (plus league average) in runs scored/allowed, team "
    "wOBA/OPS, walk/strikeout rate, ERA, FIP, and pitching K-BB% — write a tight "
    "analytical briefing (5-7 sentences). Anchor the briefing in where Boston "
    "sits leaguewide (e.g. elite run prevention vs. middling raw offense despite "
    "a good wOBA — that kind of gap is worth calling out explicitly), not just "
    "Boston's own trend. Focus on what the data implies for roster construction, "
    "sustainability of form, and regression risk. Be direct and technical, the "
    "way an analyst would write for decision-makers, not fans. No headers or "
    "bullet points, just a dense paragraph. Cite specific numbers and ranks.\n\n"
    "If you reference playoff stakes, `playoff_context` is the only authoritative "
    "source — `games_back` alone is division standing only and can be misleading "
    "(a team can be far back in the division while holding a Wild Card spot). "
    "Never call a team eliminated or say it has nothing to play for unless "
    "`playoff_context.summary` says so. Write in natural prose — never name a JSON field or key."
)


def generate_front_office_analysis(trends_summary: dict) -> str:
    message = _create_message(
        model=MODEL,
        max_tokens=700,
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
    "pitcher's season stats vs. their last-15-day stats (wOBA, BABIP, BB%/K%, ISO "
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


PLAYER_HIGHLIGHT_SYSTEM_PROMPT = (
    "You are writing a 'Player Highlight' feature for a Red Sox fan website — "
    "a condensed, warm version of a Wikipedia 'early life' + 'career' summary, "
    "written so a fan can get the highlights of this player's story in under a "
    "minute. You're given verified biographical data as JSON (birthplace, "
    "height/weight, bats/throws, draft year, MLB debut date, position, jersey "
    "number) for a player currently on the Boston Red Sox 40-man roster.\n\n"
    "Write exactly three short paragraphs (2-4 sentences each), separated by "
    "a blank line, with no headers or bullet points:\n"
    "1. Background: where they're from, and — using general, well-established "
    "public knowledge — their amateur path (high school/college/international) "
    "toward being drafted or signed. If you aren't confident of specifics "
    "beyond the verified draft year, keep this general rather than inventing "
    "detail.\n"
    "2. The climb: their path through the minors to their MLB debut (use the "
    "verified debut date) and what they've been doing since, in broad strokes.\n"
    "3. Color: one or two genuine, well-known fun facts, a nickname, or a "
    "memorable moment — ONLY if you are confident it's real and specific to "
    "this player. If you don't have confident, specific knowledge here, write "
    "something true and general instead (e.g. their draft round if notable, "
    "a real physical/statistical trait, hometown pride) rather than inventing "
    "a plausible-sounding but unverified nickname, quote, or anecdote.\n\n"
    "ACCURACY IS THE PRIORITY OVER COLOR. This is a real, named public figure "
    "on a real website — a fabricated 'fun fact' that turns out false is a "
    "real problem, a boring-but-true sentence is not. When you're not certain, "
    "default to the verified fields (birthplace, draft year, debut date, "
    "physical details) rather than invented specifics. Do not state a specific "
    "college, draft round/pick number, award, or nickname unless you are "
    "genuinely confident it is correct for this exact player. Write in warm, "
    "readable prose, not encyclopedic tone. Don't repeat the player's full "
    "name more than twice total."
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
