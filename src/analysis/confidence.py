"""Confidence scorer 0–100 for a LoL match prediction."""
from __future__ import annotations

from src.models import MatchMarket, MatchPrediction

WEIGHTS = {
    "data_quality": 0.30,
    "elo_spread": 0.25,
    "form_consistency": 0.20,
    "calibration": 0.15,
    "liquidity": 0.10,
}


def _data_quality_score(prediction: MatchPrediction) -> float:
    min_games = min(prediction.team_a_matches, prediction.team_b_matches)
    return min(100.0, min_games * 5.0)  # 20 games → 100


def _elo_spread_score(prediction: MatchPrediction) -> float:
    spread = abs(prediction.elo_a - prediction.elo_b)
    return min(100.0, spread / 4.0)  # 400 ELO diff → 100


def _form_consistency_score(prediction: MatchPrediction) -> float:
    # Reward when ELO and form agree (both predict same winner)
    elo_winner = prediction.p_elo >= 0.5
    form_winner = prediction.p_form >= 0.5
    if elo_winner == form_winner:
        return 80.0
    return 30.0


def _calibration_score(calibration_accuracy: float) -> float:
    return max(0.0, min(100.0, calibration_accuracy * 100))


def _liquidity_score(market: MatchMarket) -> float:
    return min(100.0, market.liquidity / 10.0)  # $1000 → 100


def score(
    market: MatchMarket,
    prediction: MatchPrediction,
    calibration_accuracy: float = 0.5,
) -> float:
    components = {
        "data_quality": _data_quality_score(prediction),
        "elo_spread": _elo_spread_score(prediction),
        "form_consistency": _form_consistency_score(prediction),
        "calibration": _calibration_score(calibration_accuracy),
        "liquidity": _liquidity_score(market),
    }
    total = sum(WEIGHTS[k] * v for k, v in components.items())
    return round(total, 1)
