"""Calculates P(team_a wins) from ELO, recent form, and head-to-head data."""
from __future__ import annotations

import pandas as pd
from loguru import logger

from src.data.elo_engine import (
    elo_win_probability,
    get_team_rating,
    recent_form_probability,
)
from src.data.oracle_elixir import get_head_to_head
from src.models import MatchMarket, MatchPrediction


def calculate_win_probability(
    market: MatchMarket,
    ratings: dict,
    match_df: pd.DataFrame,
    weights: dict,
    min_h2h: int = 5,
    form_window: int = 10,
    form_decay: float = 0.85,
) -> MatchPrediction:
    team_a = market.team_a
    team_b = market.team_b

    rating_a = get_team_rating(ratings, team_a)
    rating_b = get_team_rating(ratings, team_b)

    elo_a = rating_a["elo"]
    elo_b = rating_b["elo"]
    games_a = rating_a["games"]
    games_b = rating_b["games"]
    recent_a = rating_a.get("recent", [])
    recent_b = rating_b.get("recent", [])

    # Component 1: ELO
    p_elo = elo_win_probability(elo_a, elo_b)

    # Component 2: Recent form
    p_form = recent_form_probability(recent_a, recent_b, decay=form_decay, window=form_window)

    # Component 3: Head-to-head
    h2h = get_head_to_head(match_df, team_a, team_b)
    if h2h["total"] >= min_h2h:
        total = h2h["total"]
        p_h2h = h2h["a_wins"] / total if total > 0 else 0.5
    else:
        p_h2h = p_elo  # fall back to ELO when insufficient history

    p_final = (
        weights["elo"] * p_elo
        + weights["recent_form"] * p_form
        + weights["head_to_head"] * p_h2h
    )
    p_final = max(0.02, min(0.98, p_final))

    # Confidence: based on data availability
    min_games = min(games_a, games_b)
    data_confidence = min(1.0, min_games / 20)  # saturates at 20+ games
    elo_spread = abs(elo_a - elo_b) / 400.0     # normalized spread
    elo_confidence = min(1.0, elo_spread)

    confidence_raw = 0.5 * data_confidence + 0.5 * elo_confidence
    confidence = round(confidence_raw * 100, 1)

    return MatchPrediction(
        team_a=team_a,
        team_b=team_b,
        p_a_wins=p_final,
        p_elo=p_elo,
        p_form=p_form,
        p_h2h=p_h2h,
        elo_a=elo_a,
        elo_b=elo_b,
        team_a_matches=games_a,
        team_b_matches=games_b,
        confidence=confidence,
    )
