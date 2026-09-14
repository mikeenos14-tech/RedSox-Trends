from __future__ import annotations


def _find_split(splits: list[dict], split_type: str) -> dict | None:
    return next((s for s in splits if s.get("type") == split_type), None)


def _run_diff(games: list[dict]) -> int:
    return sum(
        g["our_score"] - g["their_score"]
        for g in games
        if g["our_score"] is not None and g["their_score"] is not None
    )


def _summarize_recent_games(games: list[dict]) -> dict:
    last_10 = games[-10:]
    prev_10 = games[-20:-10]

    last_10_wins = sum(1 for g in last_10 if g["won"])
    last_10_losses = len(last_10) - last_10_wins

    return {
        "last_10_record": f"{last_10_wins}-{last_10_losses}",
        "last_10_run_diff": _run_diff(last_10),
        "prev_10_run_diff": _run_diff(prev_10) if prev_10 else None,
        "trending": (
            "improving"
            if prev_10 and _run_diff(last_10) > _run_diff(prev_10)
            else "cooling off"
            if prev_10 and _run_diff(last_10) < _run_diff(prev_10)
            else "steady"
        ),
    }


def _rolling_run_diff_series(games: list[dict], window: int = 10) -> list[dict]:
    """Rolling N-game run differential, one point per game, for charting."""
    series = []
    for i, g in enumerate(games):
        if g["our_score"] is None or g["their_score"] is None:
            continue
        window_games = games[max(0, i - window + 1) : i + 1]
        series.append(
            {
                "date": g["date"],
                "rolling_run_diff": _run_diff(window_games),
            }
        )
    return series


def _strength_of_schedule(games: list[dict], win_pcts: dict[int, float] | None, last_n: int = 15) -> dict | None:
    if not win_pcts:
        return None

    recent = games[-last_n:]
    pcts = [win_pcts[g["opponent_id"]] for g in recent if g.get("opponent_id") in win_pcts]
    if not pcts:
        return None

    return {
        "games_considered": len(pcts),
        "avg_opponent_win_pct": round(sum(pcts) / len(pcts), 3),
    }


def _playoff_context(standings: dict) -> dict:
    """A deterministic, unambiguous read on playoff positioning — computed
    in code rather than left for the model to infer from raw numbers, since
    'games back' in the division and Wild Card standing are easy to conflate
    (a team can be far back in its division while comfortably holding a
    Wild Card spot, which is a very different story than 'nothing to play
    for')."""
    has_wildcard = bool(standings.get("hasWildcard"))
    division_leader = bool(standings.get("divisionLeader"))
    clinched = bool(standings.get("clinched"))
    wc_gb = standings.get("wildCardGamesBack")
    elim_num = standings.get("eliminationNumber")
    wc_elim_num = standings.get("wildCardEliminationNumber")

    is_eliminated = elim_num in ("0", "E") and wc_elim_num in ("0", "E")

    if clinched:
        summary = "Has already clinched a playoff spot."
    elif is_eliminated:
        summary = "Mathematically eliminated from playoff contention."
    elif division_leader:
        summary = "Currently leads their division."
    elif has_wildcard:
        summary = f"Currently HOLDS a Wild Card spot, {wc_gb} games clear of the cutoff line."
    elif wc_gb is not None:
        summary = f"Chasing a Wild Card spot, {wc_gb} games back of the cutoff line."
    else:
        summary = "Playoff positioning unclear from available data."

    return {
        "currently_holds_wildcard_spot": has_wildcard,
        "division_leader": division_leader,
        "clinched": clinched,
        "wildcard_games_back": wc_gb,
        "elimination_number": elim_num,
        "wildcard_elimination_number": wc_elim_num,
        "summary": summary,
    }


def build_trends_summary(
    standings: dict,
    games: list[dict],
    win_pcts: dict[int, float] | None = None,
) -> dict:
    records = standings.get("records", {})
    splits = records.get("splitRecords", [])
    home = _find_split(splits, "home")
    away = _find_split(splits, "away")
    last_ten = _find_split(splits, "lastTen")
    vs_lhp = _find_split(splits, "left")
    vs_rhp = _find_split(splits, "right")
    one_run = _find_split(splits, "oneRun")
    extra_innings = _find_split(splits, "extraInning")

    expected_records = records.get("expectedRecords", [])
    xwl = next((e for e in expected_records if e.get("type") == "xWinLoss"), None)

    runs_scored = standings.get("runsScored")
    runs_allowed = standings.get("runsAllowed")

    def wl(split: dict | None) -> dict | None:
        return {"wins": split["wins"], "losses": split["losses"]} if split else None

    return {
        "team": standings["team"]["name"],
        "record": standings.get("leagueRecord"),
        "division_rank": standings.get("divisionRank"),
        "games_back": standings.get("gamesBack"),
        "wildcard_games_back": standings.get("wildCardGamesBack"),
        "playoff_context": _playoff_context(standings),
        "streak": (standings.get("streak") or {}).get("streakCode"),
        "last_10": wl(last_ten),
        "home_record": wl(home),
        "away_record": wl(away),
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "run_differential": (runs_scored or 0) - (runs_allowed or 0),
        "expected_record": {"wins": xwl["wins"], "losses": xwl["losses"]} if xwl else None,
        "recent_form": _summarize_recent_games(games),
        "recent_games": games[-15:],
        "analysis": {
            "vs_lhp_record": wl(vs_lhp),
            "vs_rhp_record": wl(vs_rhp),
            "one_run_record": wl(one_run),
            "extra_innings_record": wl(extra_innings),
            "strength_of_schedule": _strength_of_schedule(games, win_pcts),
            "rolling_run_diff_series": _rolling_run_diff_series(games),
        },
    }
