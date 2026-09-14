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
