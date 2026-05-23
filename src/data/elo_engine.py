"""ELO rating engine trained on Oracle's Elixir match history."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

RATINGS_PATH = Path("data/team_ratings.json")
INITIAL_ELO = 1500.0
K_FACTOR = 32
DECAY_HALFLIFE_DAYS = 180


def _expected_score(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def _decay_weight(match_date: datetime, reference: datetime, halflife_days: int = DECAY_HALFLIFE_DAYS) -> float:
    days_ago = (reference - match_date).days
    return math.exp(-math.log(2) * days_ago / halflife_days)


def build_ratings(df: pd.DataFrame) -> dict[str, dict]:
    """Build ELO ratings from match dataframe. Returns {team_name: {elo, games, wins, recent}}."""
    ratings: dict[str, float] = {}
    games: dict[str, int] = {}
    wins: dict[str, int] = {}
    recent: dict[str, list[int]] = {}  # newest first
    last_seen: dict[str, datetime] = {}

    reference = datetime.utcnow()

    for _, row in df.iterrows():
        team = row["teamname"]
        result = int(row["result"])
        match_date = row["date"]
        game_id = row.get("gameid", "")

        if team not in ratings:
            ratings[team] = INITIAL_ELO
            games[team] = 0
            wins[team] = 0
            recent[team] = []

        games[team] += 1
        if result == 1:
            wins[team] += 1
        recent[team] = ([result] + recent[team])[:20]  # keep last 20
        last_seen[team] = match_date

    # Second pass: ELO updates need opponent — match pairs by game_id
    elo: dict[str, float] = {t: INITIAL_ELO for t in ratings}
    game_rows: dict[str, list] = {}
    for _, row in df.iterrows():
        gid = str(row.get("gameid", ""))
        if gid not in game_rows:
            game_rows[gid] = []
        game_rows[gid].append(row)

    for gid, rows in game_rows.items():
        if len(rows) != 2:
            continue
        r0, r1 = rows[0], rows[1]
        t0, t1 = r0["teamname"], r1["teamname"]
        res0 = int(r0["result"])
        match_date = r0["date"] if hasattr(r0["date"], "year") else reference
        w = _decay_weight(match_date, reference)

        e0 = _expected_score(elo.get(t0, INITIAL_ELO), elo.get(t1, INITIAL_ELO))
        e1 = 1.0 - e0
        elo[t0] = elo.get(t0, INITIAL_ELO) + w * K_FACTOR * (res0 - e0)
        elo[t1] = elo.get(t1, INITIAL_ELO) + w * K_FACTOR * ((1 - res0) - e1)

    result_dict = {}
    for team in ratings:
        result_dict[team] = {
            "elo": round(elo.get(team, INITIAL_ELO), 2),
            "games": games[team],
            "wins": wins[team],
            "recent": recent[team],
            "last_seen": last_seen.get(team, reference).isoformat(),
        }

    logger.info(f"Built ELO ratings for {len(result_dict)} teams")
    return result_dict


def save_ratings(ratings: dict) -> None:
    RATINGS_PATH.parent.mkdir(exist_ok=True)
    with open(RATINGS_PATH, "w") as f:
        json.dump(ratings, f, indent=2)


def load_ratings() -> dict[str, dict]:
    if not RATINGS_PATH.exists():
        return {}
    with open(RATINGS_PATH) as f:
        return json.load(f)


def get_team_rating(ratings: dict, team: str) -> dict:
    """Return rating entry, or default if unknown."""
    return ratings.get(team, {"elo": INITIAL_ELO, "games": 0, "wins": 0, "recent": [], "last_seen": None})


def elo_win_probability(elo_a: float, elo_b: float) -> float:
    return _expected_score(elo_a, elo_b)


def recent_form_probability(recent_a: list[int], recent_b: list[int], decay: float = 0.85, window: int = 10) -> float:
    """Recency-weighted win rate for each team, converted to relative probability."""
    def weighted_wr(results: list[int]) -> float:
        if not results:
            return 0.5
        results = results[:window]
        weights = [decay ** i for i in range(len(results))]
        return sum(r * w for r, w in zip(results, weights)) / sum(weights)

    wr_a = weighted_wr(recent_a)
    wr_b = weighted_wr(recent_b)
    total = wr_a + wr_b
    if total == 0:
        return 0.5
    return wr_a / total
