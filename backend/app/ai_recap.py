import json
import logging
import re

import anthropic
from anthropic import AsyncAnthropic

from . import config

MODEL = "claude-sonnet-5"

logger = logging.getLogger("uvicorn.error")


def _client() -> AsyncAnthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )
    return AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def _create_message(**kwargs):
    """Wraps client.messages.create() and converts the Anthropic SDK's own
    exception types (AuthenticationError, RateLimitError, APIConnectionError,
    etc. — none of which are RuntimeError subclasses) into RuntimeError, so
    a single `except RuntimeError` at the route level reliably catches every
    failure mode instead of some falling through as unhandled 500s.

    Uses AsyncAnthropic specifically: the sync client's blocking HTTP call
    would freeze this whole single-process event loop for every concurrent
    request (not just this one) for the several seconds a Claude call takes,
    every time one of these generation calls misses its cache.
    """
    try:
        return await _client().messages.create(**kwargs)
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


ANALYSIS_SYSTEM_PROMPT = (
    "You are a well-educated, highly literate Boston Red Sox fan who happens "
    "to be sharp with stats — think a dryly funny columnist, not a fan "
    "shouting from the bleachers — writing the one AI-generated read a "
    "fellow fan who follows the team closely will see on this page. It needs "
    "to work as both a quick status check and a real analytical take, since "
    "there's no separate summary elsewhere. Understated dry wit is welcome "
    "where it fits naturally, delivered in precise vocabulary and clean "
    "grammar, but this is still the hard analytical section of the site — "
    "never let a joke blur a real number or a genuine risk. Given "
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
    "speaking vaguely — confident and analytical, with the voice of a fan who "
    "actually knows the numbers, not a dry front-office memo, and don't shy "
    "from technical detail either. Output exactly one bullet per line, each "
    "starting with '- ', no headers, no preamble or closing remarks.\n\n"
    "If you reference playoff stakes, `playoff_context` is the only authoritative "
    "source — `games_back` alone is division standing only and can be misleading "
    "(a team can be far back in the division while holding a Wild Card spot). "
    "Never call a team eliminated or say it has nothing to play for unless "
    "`playoff_context.summary` says so. Write in natural prose — never name a JSON field or key.\n\n"
    "SEASON PHASE: if `postseason` is present (not null), the regular season "
    "is OVER and every regular-season number is final. Write about it in the "
    "past tense ('finished 87-75') and never as a race still in progress — no "
    "seeding, cushions, magic numbers, or 'what's left to play for.' Bullet 3 "
    "becomes what the underlying numbers say about how good this team really "
    "is heading into (or out of) October, not a gap the standings 'should "
    "close.' Bullet 4 must cover the postseason, using only the `postseason` "
    "block: the series and opponent, `status` (MLB's own series standing; "
    "null means the series hasn't started yet), `phase` (in_series, "
    "awaiting_next_round, eliminated, or won_world_series), and `next_game`. "
    "Never invent a postseason result, matchup, or starting pitcher that "
    "isn't given."
)


async def generate_team_analysis(trends_summary: dict) -> str:
    message = await _create_message(
        model=MODEL,
        # Seen this hit the ceiling in production once (966 chars of visible
        # text but stop_reason=max_tokens — token budget burned on something
        # other than the 4 bullets themselves, not just a longer-than-usual
        # answer). Raising the cap costs nothing since billing is by tokens
        # actually generated, not the ceiling.
        max_tokens=2500,
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
    "You are a well-educated, highly literate Boston Red Sox fan who tracks "
    "every player's peripherals like a stathead — think a dryly witty "
    "columnist, precise with both numbers and words — reviewing player-level "
    "form data for every player on the active roster with a large enough "
    "recent sample to be meaningful. A dry one-liner is welcome, delivered "
    "with excellent grammar and vocabulary, not slang or forced needling — "
    "but every verdict still has to be backed by the real numbers, never a "
    "joke standing in for one. Given "
    "JSON with each hitter's and "
    "pitcher's season stats vs. their last-15-games-played stats (wOBA, BABIP, BB%/K%, ISO "
    "for hitters; ERA, FIP, K-BB%, BABIP-against, strand rate for pitchers), pick "
    "ONLY the 3-5 single most notable form changes across the whole list (hot or "
    "cold, whichever stand out most — don't force an even split). For each, say "
    "in one tight sentence whether the peripherals (BABIP, FIP vs ERA, K%/BB%) "
    "suggest the change is real or likely to regress. League-average BABIP is "
    "roughly .300. Fields ending in _pct are already percentages (11.0 means "
    "11.0%) — write them with a % sign; wOBA/BABIP/ISO are rate stats written "
    "baseball-style ('.311'). `pa`/`ip` are sample sizes: weigh them, and "
    "never call a small sample reliable. Output exactly one bullet per "
    "player, each starting with '- ', in this exact shape: '- Name (pos/role): "
    "one sentence of verdict with the 1-2 key numbers woven into it.' State "
    "each number once — never repeat numbers after the sentence. Plain text "
    "only — no markdown bold/italics, no headers, no preamble or closing "
    "remarks. Keep the whole thing under 120 words total."
)


async def generate_player_notes(player_report: dict) -> str:
    if not player_report["hitters"] and not player_report["pitchers"]:
        return "- Not enough recent playing time across the roster yet to call out a form change with confidence."

    message = await _create_message(
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


SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are a well-educated, highly literate Boston Red Sox fan — think a "
    "dryly funny columnist with excellent grammar and vocabulary, not "
    "someone shouting from the bleachers — writing the 'What Stood Out' "
    "callouts for a Red Sox fan website, shown right after a recap of the "
    "team's most recent game. You are given a JSON list of real, already-"
    "computed facts about that game — streaks, rare stat lines, career "
    "milestones — each as a plain sentence. These facts are the ONLY things "
    "you're allowed to mention; never add a stat, date, or detail that isn't "
    "already stated in one of them, and never invent why something is "
    "significant beyond what the sentence already says.\n\n"
    "If there are more than 3 facts, pick the 3 most genuinely interesting to "
    "a devoted fan (a career milestone or a long streak snapping usually "
    "outranks a single big game) — you may drop the rest, but never add to "
    "them. Rewrite each kept fact as one crisp, well-crafted sentence — dry "
    "wit is welcome where it fits naturally, but never at the cost of clarity "
    "or precision (you can rephrase for flow, but every number and name must "
    "still match the original exactly). Output one bullet per fact, each "
    "starting with '- ', no intro or closing remarks, no markdown formatting "
    "beyond the bullet dash."
)


async def generate_significance_narration(findings: list[dict]) -> str:
    message = await _create_message(
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
    "You are a well-educated, highly literate Boston Red Sox fan — think a "
    "dryly witty columnist with excellent grammar and vocabulary — writing a "
    "'Player Highlight' feature for a Red Sox fan website: a condensed, "
    "warm version of a Wikipedia 'early life' + 'career' summary, written so "
    "a fellow fan can get the highlights of this player's story in under a "
    "minute, with real numbers backing it up. Understated dry wit is "
    "welcome, but this is still a factual profile first — never let a joke "
    "replace or blur a real number. You're given verified data as "
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
    "3. Color: if verified_nickname is present, use it here confidently. "
    "Explain where it came from ONLY using verified_nickname_origin, in a "
    "single clause, adding no detail of your own (no positions, moments, or "
    "anecdotes it doesn't state); if that field is null, don't explain or "
    "speculate about the origin at all — just use the nickname. Otherwise, "
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
    "you're genuinely confident is real for this exact player — and never "
    "add a hometown, high school, or town that isn't in the verified data "
    "(the birthplace field is the only hometown you have). Skip filler about "
    "how or why he joined the Red Sox; you aren't given that. Write in "
    "warm, literate, precisely-worded prose, not encyclopedic tone. Don't "
    "repeat the player's full name more than twice total."
)


async def generate_player_highlight(bio: dict) -> str:
    message = await _create_message(
        model=MODEL,
        # Same headroom bump as generate_team_analysis, for the same reason —
        # comparable output length (three paragraphs vs. four bullets) on the
        # same 1500 ceiling that's already been seen to run out once.
        max_tokens=2500,
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
    "You are a well-educated, highly literate Boston Red Sox fan — think a "
    "sharp, dryly funny columnist, not someone shouting from the bleachers. "
    "Excellent grammar and precise vocabulary throughout; wit should be "
    "understated and exact, never a forced quip or slang-heavy aside. Given "
    "a verified fact sheet for one game — final score, every scoring play in "
    "order with the score after it and any lead changes already marked, "
    "every pitcher's full line with their starter/reliever role, the top "
    "hitters, and real news headlines — write ONE tight paragraph (4-6 "
    "sentences) recapping the game for a fellow fan "
    "who missed it.\n\n"
    "CLARITY IS NON-NEGOTIABLE — a reader should be able to reconstruct "
    "exactly what happened from your paragraph alone, on one read. Describe "
    "events in plain chronological order rather than looping back ('X "
    "happened, but earlier Y had already...'). Always name a player directly "
    "when you know their name from the data — never refer to someone as "
    "another player's 'counterpart' or by role alone (e.g. 'the opposing "
    "closer') when the actual name is sitting right there in the fact sheet. Avoid "
    "stacking multiple distinct events into one overloaded clause; if a "
    "sentence needs two 'and's to hold together, split it into two "
    "sentences.\n\n"
    "The fact sheet is pre-computed and authoritative: restate its facts, "
    "never recompute them. Use its run counts exactly as given (a play that "
    "scored 1 run is never 'two-run'), describe ties and lead changes only "
    "where it marks them, and call an outing scoreless only if its line says "
    "0 R. A run scored while a reliever was pitching can be charged to the "
    "pitcher before him — for who allowed runs, go by each pitcher's R/ER. "
    "The only ballpark you may name is the one on the FINAL line. Don't "
    "characterize the standings, playoff race, or any player's history "
    "with another team — none of that is on the fact sheet.\n\n"
    "Reference specific verified facts: the score, who pitched well or "
    "struggled, who delivered the big hit, and any real storyline the "
    "article headlines point to (e.g. a milestone, an injury scare, a "
    "notable streak) — but only mention something the headlines or fact sheet "
    "actually support, never invent a specific quote, injury, or storyline "
    "that isn't backed by the data you were given. This also covers trend "
    "claims: you have data for exactly ONE game, not this team's history "
    "against this opponent, so never assert something like 'they seem to "
    "have our number in these situations' or 'this team always shows up "
    "late' — a claim about a pattern across multiple games is an invention "
    "unless an article headline explicitly says so. If the articles don't "
    "add anything beyond what the box score already shows, that's fine — "
    "just write a great box-score-grounded recap without forcing in an "
    "article detail. No headers, no bullet points, no score restated as a "
    "headline (the box score is shown separately) — just the narrative "
    "paragraph itself.\n\n"
    "POSTSEASON: if the fact sheet has a POSTSEASON line, this was a playoff game. Name it "
    "plainly once (e.g. 'Game 1 of the AL Wild Card Series') and take where "
    "the series stands only from the POSTSEASON line (MLB's own standing "
    "after this game, e.g. 'BOS leads 1-0') — never work out or guess the "
    "series state yourself, and never cite a season record or treat it as a "
    "regular-season game."
)


STATCAST_SYSTEM_PROMPT = (
    "You are a well-educated, highly literate Boston Red Sox fan who nerds "
    "out on Statcast data (real, measured batted-ball and pitch-tracking "
    "data from Baseball Savant — exit velocity, barrel rate, xwOBA, xERA, "
    "whiff rate, sprint speed, etc.) for the Boston Red Sox roster — the "
    "kind of fan who'll gladly explain, in precise and grammatically clean "
    "prose, why a guy's exit velo says more than his batting average. "
    "Understated dry wit is welcome, but every finding still has to trace to "
    "a real number, never a joke standing in for one. Given JSON with each "
    "player's percentile rank (0-100, always "
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


async def generate_statcast_notes(report: dict) -> str:
    if not report["hitters"] and not report["pitchers"]:
        return "- Not enough Statcast-qualified playing time on the roster yet to call out a trend."

    message = await _create_message(
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


def _ordinal_inning(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_recap_fact_sheet(game: dict) -> str:
    """The game as plain, pre-computed English sentences — scoring sequence
    with running score, lead changes, and every pitcher's full line spelled
    out. Built in code because, handed raw JSON, the model repeatedly
    miscounted (an RBI double became "two-run," a 1-run relief outing became
    "scoreless," a 3-2 game became "a 2-2 tie"). Restating clear facts is
    reliable; deriving them from nested numbers is not."""
    # Full opponent name: a last-word short form breaks on "White Sox" /
    # "Blue Jays" ("Sox", "Jays").
    us, them = "Red Sox", game["opponent"]
    lines = [
        f"FINAL: {us} {game['our_score']}, {game['opponent']} {game['their_score']} "
        f"({'Red Sox win' if game['won'] else 'Red Sox loss'}; {'home' if game['home_or_away'] == 'home' else 'road'} game"
        f"{', at ' + game['venue'] if game.get('venue') else ''})."
    ]
    ps = game.get("postseason")
    if ps:
        lines.append(f"POSTSEASON: {ps['series']}, Game {ps['game_number']}. Series standing after this game: {ps['status'] or 'n/a'}.")

    lines.append("\nSCORING, IN ORDER (runs on the play, then the score after it):")
    leader = None
    for play in game.get("scoring_plays", []):
        sa = play["score_after"]
        batting = us if play["team_batting"] == "us" else them
        runs = play["runs_on_play"]
        lines.append(
            f"- {play['half'].capitalize()} {_ordinal_inning(play['inning'])}, {batting} scored {runs} "
            f"run{'s' if runs != 1 else ''} ({play['pitcher_on_mound']} pitching): {play['description']} "
            f"Score: {us} {sa['us']}, {them} {sa['them']}."
        )
        now = "us" if sa["us"] > sa["them"] else "them" if sa["them"] > sa["us"] else None
        if now != leader:
            if now is None:
                lines.append("  -> This play TIED the game.")
            else:
                lines.append(f"  -> {us if now == 'us' else them} {'took the lead' if leader is None else 'took the lead back'} here.")
            leader = now
    if not game.get("scoring_plays"):
        lines.append("- (scoring plays unavailable)")

    lines.append("\nPITCHERS (in order of appearance; R = all runs charged, ER = earned runs charged):")
    for side, team in (("us", us), ("them", them)):
        for p in game.get("pitching", {}).get(side, []):
            decision = f" — {p['note'].strip('() ')}" if p.get("note") else ""
            lines.append(
                f"- {team}: {p['name']} ({p['role']}): {p['innings_pitched']} IP, {p.get('hits')} H, "
                f"{p.get('runs')} R, {p.get('earned_runs')} ER, {p.get('walks')} BB, {p.get('strikeouts')} K{decision}"
                + ("  [allowed no runs]" if not p.get("runs") else "")
            )

    lines.append("\nTOP HITTERS (box-score line: H-AB | extras):")
    for side, team in (("us", us), ("them", them)):
        for b in game.get("top_performers", {}).get(side, []):
            lines.append(f"- {team}: {b['name']} {b['summary']} ({b['hits']} H, {b['home_runs']} HR, {b['rbi']} RBI)")

    if game.get("record_after"):
        lines.append(f"\nRed Sox record after this game: {game['record_after']['wins']}-{game['record_after']['losses']}.")
    arts = game.get("articles") or []
    if arts:
        lines.append("\nNEWS HEADLINES ABOUT THIS GAME (may include other recent games; use only what clearly matches):")
        lines.extend(f"- {a['title']} ({a['source']})" for a in arts)
    return "\n".join(lines)


_RUN_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_HIT_TYPES = {
    "single": "singles", "double": "doubles", "triple": "triples",
    "homer": "homers", "home run": "homers", "shot": "homers", "blast": "homers", "bomb": "homers",
}
_N_RUN_HIT_RE = re.compile(
    r"\b(one|two|three|four|[1-4])-run (single|double|triple|homer|home run|shot|blast|bomb)\b", re.IGNORECASE
)
_GRAND_SLAM_RE = re.compile(r"\bgrand slam\b", re.IGNORECASE)


def _hits_with_runs(game: dict) -> set[tuple[int, str]]:
    """(runs, verb) for every run-scoring hit, e.g. (1, "doubles")."""
    found = set()
    for play in game.get("scoring_plays", []):
        m = re.search(r"\b(singles|doubles|triples|homers)\b", play["description"])
        if m:
            found.add((play["runs_on_play"], m.group(1)))
    return found


def invalid_run_counts(text: str, game: dict) -> list[str]:
    """Phrases like "two-run double" that match no actual scoring play. A
    narrow, mechanical backstop: the model kept writing "two-run double" for
    a play the fact sheet explicitly marks as 1 run, despite prompt rules —
    so the count is checked in code, not trusted."""
    allowed = _hits_with_runs(game)
    bad = [
        m.group(0)
        for m in _N_RUN_HIT_RE.finditer(text)
        if (_RUN_WORDS[m.group(1).lower()], _HIT_TYPES[m.group(2).lower()]) not in allowed
    ]
    if _GRAND_SLAM_RE.search(text) and (4, "homers") not in allowed:
        bad.append("grand slam")
    # The model's prior pulls every Red Sox game to Fenway; flag it when the
    # fact sheet's venue says otherwise (retry only — no safe mechanical fix).
    if "fenway" in text.lower() and "fenway" not in (game.get("venue") or "").lower():
        bad.append("Fenway")
    return bad


def _strip_run_counts(text: str, bad: list[str]) -> str:
    # "two-run double" -> "double": always true, never wrong.
    for phrase in bad:
        text = re.sub(rf"\b{re.escape(phrase)}\b", _N_RUN_HIT_RE.sub(r"\2", phrase) if phrase != "grand slam" else "home run", text)
    return text


async def generate_game_recap(game_data: dict) -> str:
    sheet = build_recap_fact_sheet(game_data)

    async def attempt() -> str:
        message = await _create_message(
            model=MODEL,
            max_tokens=700,
            system=GAME_RECAP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Game fact sheet:\n{sheet}"}],
        )
        return _extract_text(message)

    text = await attempt()
    if invalid_run_counts(text, game_data):
        text = await attempt()
    bad = invalid_run_counts(text, game_data)
    if bad:
        logger.warning("Recap for game %s still has unsupported claims after retry: %s", game_data.get("game_pk"), bad)
        text = _strip_run_counts(text, [b for b in bad if b != "Fenway"])
    return text
