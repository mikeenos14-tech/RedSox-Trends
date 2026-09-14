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


def build_trends_summary(standings: dict, games: list[dict]) -> dict:
    records = standings.get("records", {})
    splits = records.get("splitRecords", [])
    home = _find_split(splits, "home")
    away = _find_split(splits, "away")
    last_ten = _find_split(splits, "lastTen")

    expected_records = records.get("expectedRecords", [])
    xwl = next((e for e in expected_records if e.get("type") == "xWinLoss"), None)

    runs_scored = standings.get("runsScored")
    runs_allowed = standings.get("runsAllowed")

    return {
        "team": standings["team"]["name"],
        "record": standings.get("leagueRecord"),
        "division_rank": standings.get("divisionRank"),
        "games_back": standings.get("gamesBack"),
        "wildcard_games_back": standings.get("wildCardGamesBack"),
        "streak": (standings.get("streak") or {}).get("streakCode"),
        "last_10": {"wins": last_ten["wins"], "losses": last_ten["losses"]} if last_ten else None,
        "home_record": {"wins": home["wins"], "losses": home["losses"]} if home else None,
        "away_record": {"wins": away["wins"], "losses": away["losses"]} if away else None,
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "run_differential": (runs_scored or 0) - (runs_allowed or 0),
        "expected_record": {"wins": xwl["wins"], "losses": xwl["losses"]} if xwl else None,
        "recent_form": _summarize_recent_games(games),
        "recent_games": games[-15:],
    }
