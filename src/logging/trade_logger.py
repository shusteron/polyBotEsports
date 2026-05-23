"""Structured event logging for the esports bot."""
from __future__ import annotations

from loguru import logger

from src.models import MatchMarket, MatchPrediction, TradeSignal


def log_scan_start(n_markets: int) -> None:
    logger.info(f"Market scan started — evaluating {n_markets} LoL markets")


def log_market_analysis(market: MatchMarket, prediction: MatchPrediction, edge: float, confidence: float) -> None:
    logger.debug(
        f"ANALYSIS | {market.team_a} vs {market.team_b} | "
        f"p_model={prediction.p_a_wins:.3f} p_market={market.yes_price:.3f} "
        f"edge={edge:+.3f} conf={confidence:.1f} | {market.region}"
    )


def log_no_trade(market: MatchMarket, reasons: list[str]) -> None:
    logger.debug(f"NO_TRADE | {market.team_a} vs {market.team_b} | {'; '.join(reasons)}")


def log_trade(signal: TradeSignal, size: float) -> None:
    logger.info(
        f"SIGNAL | {signal.action.value} ${size:.2f} | "
        f"{signal.market.team_a} vs {signal.market.team_b} | "
        f"edge={signal.edge:+.3f} conf={signal.confidence:.1f} | {signal.market.region}"
    )


def log_status(capital: float, portfolio_value: float, open_positions: int, pnl_summary: dict) -> None:
    logger.info(
        f"STATUS | capital=${capital:.2f} | portfolio=${portfolio_value:.2f} | "
        f"open={open_positions} | pnl=${pnl_summary['total_pnl']:.2f} | "
        f"win_rate={pnl_summary['win_rate']:.1%} | trades={pnl_summary['n_trades']}"
    )
