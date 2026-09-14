import json

from anthropic import Anthropic

from . import config

MODEL = "claude-sonnet-5"

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
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Season trend data:\n{json.dumps(trends_summary, indent=2)}",
            }
        ],
    )

    return "".join(block.text for block in message.content if block.type == "text")


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
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Trend data:\n{json.dumps(trends_summary, indent=2)}",
            }
        ],
    )

    return "".join(block.text for block in message.content if block.type == "text")


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
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )

    if not headlines:
        return "- No recent headlines found in the last few days."

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    slim = [{"title": h["title"], "source": h["source"]} for h in headlines]

    message = client.messages.create(
        model=MODEL,
        max_tokens=350,
        system=HEADLINES_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Recent headlines:\n{json.dumps(slim, indent=2)}",
            }
        ],
    )

    return "".join(block.text for block in message.content if block.type == "text")
