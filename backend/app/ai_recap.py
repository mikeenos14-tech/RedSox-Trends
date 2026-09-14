import json

from anthropic import Anthropic

from . import config

MODEL = "claude-sonnet-5"


def _client() -> Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _extract_text(message) -> str:
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text or message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Response was truncated (stop_reason={message.stop_reason}, "
            f"got {len(text)} chars of text). Try again — the prompt may need "
            "a larger max_tokens budget."
        )
    return text


SYSTEM_PROMPT = (
    "You are a sharp, knowledgeable beat writer covering the Boston Red Sox. "
    "Given structured season-trend data as JSON, write a short recap (4-6 sentences) "
    "in a confident, analytical voice for a fan who follows the team closely. "
    "Reference specific numbers from the data (record, streak, run differential, "
    "home/away splits, expected vs. actual record) rather than speaking vaguely. "
    "Call out whether the underlying trends (run differential, expected record) "
    "support or contradict the team's recent results. No headers, no bullet points, "
    "just a tight paragraph."
)


def generate_recap(trends_summary: dict) -> str:
    message = _client().messages.create(
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
    "(regression/luck indicators), strength of recent schedule, and a rolling "
    "run-differential series — write a tight analytical briefing (4-6 sentences). "
    "Focus on what the data implies for roster construction, sustainability of "
    "the team's form, and regression risk. Be direct and technical, the way an "
    "analyst would write for decision-makers, not fans. No headers or bullet "
    "points, just a dense paragraph. Cite specific numbers."
)


def generate_front_office_analysis(trends_summary: dict) -> str:
    message = _client().messages.create(
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
    "player-level form data. Given JSON with each rostered hitter's and pitcher's "
    "season stats vs. their last-15-day stats (wOBA, BABIP, BB%/K%, ISO for "
    "hitters; ERA, FIP, K-BB%, BABIP-against, strand rate for pitchers), pick ONLY "
    "the 3-5 single most notable form changes across the whole roster (hot or "
    "cold, whichever stand out most — don't force an even split). Skip anyone "
    "whose recent sample is flagged small_sample. For each, say in one tight "
    "sentence whether the peripherals (BABIP, FIP vs ERA, K%/BB%) suggest the "
    "change is real or likely to regress. League-average BABIP is roughly .300. "
    "Output exactly one bullet per player, each starting with '- ', in this exact "
    "shape: '- Name (pos/role): one sentence of verdict + the 1-2 key numbers "
    "backing it up.' Plain text only — no markdown bold/italics, no headers, no "
    "preamble or closing remarks. Keep the whole thing under 120 words total."
)


def generate_player_notes(player_report: dict) -> str:
    message = _client().messages.create(
        model=MODEL,
        max_tokens=4000,
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

    message = _client().messages.create(
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
