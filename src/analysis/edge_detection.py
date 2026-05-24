"""Edge calculation between model probability and market odds."""
from __future__ import annotations

from src.models import MatchMarket, MatchPrediction


def calculate_edge(prediction: MatchPrediction, market: MatchMarket) -> tuple[float, float, str]:
    """
    Returns (model_prob, market_prob, side).
    side = 'YES' if we should bet YES (team_a wins), 'NO' otherwise.
    """
    p_model_yes = prediction.p_a_wins   # our P(team_a wins) == P(YES)
    p_market_yes = market.yes_price

    edge_yes = p_model_yes - p_market_yes
    edge_no = (1 - p_model_yes) - market.no_price

    # Pick the side with the highest POSITIVE edge, not largest absolute value
    if edge_yes >= edge_no:
        return p_model_yes, p_market_yes, "YES"
    else:
        return 1 - p_model_yes, market.no_price, "NO"
