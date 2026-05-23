"""NO_TRADE gate: 9 independent rejection checks. Any failure = no trade."""
from __future__ import annotations

from datetime import datetime, timezone

from src.models import MatchMarket, MatchPrediction


def check_all(
    market: MatchMarket,
    prediction: MatchPrediction,
    model_prob: float,
    market_prob: float,
    edge: float,
    confidence: float,
    cfg: dict,
) -> list[str]:
    """Returns a list of rejection reasons. Empty list = trade approved."""
    reasons = []
    now = datetime.now(timezone.utc)
    res = market.resolution_date
    if res.tzinfo is None:
        res = res.replace(tzinfo=timezone.utc)
    hours_to_match = (res - now).total_seconds() / 3600
    days_to_match = hours_to_match / 24

    # Gate 1: Liquidity
    if market.liquidity < cfg["min_liquidity"]:
        reasons.append(f"liquidity ${market.liquidity:.0f} < ${cfg['min_liquidity']}")

    # Gate 2: Spread
    if market.spread > cfg["max_spread"]:
        reasons.append(f"spread {market.spread:.3f} > {cfg['max_spread']}")

    # Gate 3: Too close to match (in-play latency risk)
    if hours_to_match < cfg["min_hours_to_match"]:
        reasons.append(f"match in {hours_to_match:.1f}h < {cfg['min_hours_to_match']}h minimum")

    # Gate 4: Too far out (roster change risk)
    if days_to_match > cfg["max_days_to_match"]:
        reasons.append(f"match in {days_to_match:.0f}d > {cfg['max_days_to_match']}d maximum")

    # Gate 5: Insufficient historical data
    min_matches = cfg["min_team_matches"]
    if prediction.team_a_matches < min_matches:
        reasons.append(f"{prediction.team_a} only {prediction.team_a_matches} matches < {min_matches}")
    if prediction.team_b_matches < min_matches:
        reasons.append(f"{prediction.team_b} only {prediction.team_b_matches} matches < {min_matches}")

    # Gate 6: ELO confidence (too few games to trust rating)
    min_elo_games = cfg["min_elo_games"]
    if prediction.team_a_matches < min_elo_games or prediction.team_b_matches < min_elo_games:
        reasons.append("insufficient ELO history")

    # Gate 7: Coin-flip zone — model says it's basically 50/50
    buffer = cfg["coin_flip_buffer"]
    if abs(model_prob - 0.5) < buffer:
        reasons.append(f"|p={model_prob:.3f} - 0.5| < {buffer} coin-flip zone")

    # Gate 8: Edge too small
    if edge < cfg["min_edge"]:
        reasons.append(f"edge {edge:.3f} < {cfg['min_edge']}")

    # Gate 9: Confidence too low
    if confidence < cfg["min_confidence"]:
        reasons.append(f"confidence {confidence:.1f} < {cfg['min_confidence']}")

    # Gate 10: Extreme underdog — market implies <15% chance; seeded model unreliable at this price
    max_implied = cfg.get("max_market_implied_prob", 1.0)
    if market_prob < max_implied:
        reasons.append(
            f"market implies {market_prob:.1%} — extreme underdog, seeded model unreliable at this price"
        )

    return reasons
