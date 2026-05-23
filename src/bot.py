"""EsportsBot — main orchestrator. Mirrors weather bot architecture."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from src.analysis import calibration as cal_store
from src.analysis.confidence import score as confidence_score
from src.analysis.edge_detection import calculate_edge
from src.analysis.probability import calculate_win_probability
from src.data.cito_client import CitoClient
from src.data.elo_engine import build_ratings, load_ratings, save_ratings
from src.data.oracle_elixir import load_match_data
from src.execution.paper_trader import PaperTrader
from src.execution.trade_filter import check_all
from src.export.excel_exporter import export_report
from src.logging.trade_logger import (
    log_market_analysis,
    log_no_trade,
    log_scan_start,
    log_status,
    log_trade,
)
from src.market_scanner import scan_lol_markets
from src.models import MatchMarket, TradeAction, TradeSignal
from src.risk.risk_manager import RiskManager


class EsportsBot:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.paper_trader = PaperTrader(
            starting_capital=cfg["risk"]["starting_capital"],
            slippage=cfg["execution"]["simulated_slippage"],
            fee=cfg["execution"]["simulated_fee"],
        )
        self.risk_manager = RiskManager(cfg["risk"])
        self.cito = CitoClient()
        self.calibration_records = cal_store.load_calibration()
        self._ratings: dict = {}
        self._match_df: pd.DataFrame | None = None
        logger.info("EsportsBot initialized")

    def _ensure_data_loaded(self) -> None:
        if self._match_df is not None:
            return
        try:
            self._match_df = load_match_data(cache_hours=self.cfg["data_sources"]["oracle_elixir"]["cache_hours"])
        except Exception as e:
            logger.error(f"Failed to load Oracle's Elixir data: {e}")
            self._match_df = pd.DataFrame()

        if not self._match_df.empty:
            try:
                self._ratings = build_ratings(self._match_df)
                save_ratings(self._ratings)
            except Exception as e:
                logger.warning(f"ELO build failed, loading cached ratings: {e}")
                self._ratings = load_ratings()
        else:
            # No live data — use pre-seeded or previously built ratings from disk
            self._ratings = load_ratings()
            if self._ratings:
                logger.info("Live match data unavailable — using cached/seeded team ratings")

        logger.info(f"Loaded ratings for {len(self._ratings)} teams")

    def run_scan_cycle(self) -> None:
        logger.info("=== Starting LoL esports scan cycle ===")
        self._ensure_data_loaded()

        markets = scan_lol_markets()
        log_scan_start(len(markets))

        open_trades = self.paper_trader.get_open_trades()
        today = datetime.now(timezone.utc).date()
        today_trades = [
            t for t in self.paper_trader._state["trades"]
            if t.get("opened_at", "")[:10] == str(today)
        ]

        for market in markets:
            self._process_market(market, open_trades, today_trades)

        log_status(
            self.paper_trader.capital,
            self.paper_trader.get_portfolio_value(),
            len(open_trades),
            self.paper_trader.get_pnl_summary(),
        )
        logger.info("=== Scan cycle complete ===")

    def _process_market(self, market: MatchMarket, open_trades: list, today_trades: list) -> None:
        try:
            # match_df may be empty (Leaguepedia unavailable); ELO + form still work from seeded ratings
            match_df = self._match_df if self._match_df is not None else pd.DataFrame()

            prediction = calculate_win_probability(
                market=market,
                ratings=self._ratings,
                match_df=match_df,
                weights=self.cfg["probability"]["weights"],
                min_h2h=self.cfg["probability"]["min_h2h_meetings"],
                form_window=self.cfg["probability"]["form_window"],
                form_decay=self.cfg["probability"]["form_decay"],
            )

            calibration_accuracy = cal_store.get_accuracy(self.calibration_records)
            conf = confidence_score(market, prediction, calibration_accuracy)

            model_prob, market_prob, side = calculate_edge(prediction, market)
            edge = model_prob - market_prob

            log_market_analysis(market, prediction, edge, conf)

            rejection_reasons = check_all(
                market=market,
                prediction=prediction,
                model_prob=model_prob,
                market_prob=market_prob,
                edge=edge,
                confidence=conf,
                cfg=self.cfg["filters"],
            )

            if rejection_reasons:
                log_no_trade(market, rejection_reasons)
                return

            action = TradeAction.BUY_YES if side == "YES" else TradeAction.BUY_NO
            size = self.risk_manager.get_approved_size(
                prob=model_prob,
                price=market_prob,
                capital=self.paper_trader.capital,
                open_trades=open_trades,
                today_trades=today_trades,
            )

            if size <= 0:
                log_no_trade(market, ["risk manager rejected size"])
                return

            kelly_size = self.risk_manager.kelly_size(model_prob, market_prob, self.paper_trader.capital)

            signal = TradeSignal(
                action=action,
                market=market,
                prediction=prediction,
                model_probability=model_prob,
                market_probability=market_prob,
                edge=edge,
                kelly_size=kelly_size,
                recommended_size=size,
                confidence=conf,
            )

            log_trade(signal, size)
            self.paper_trader.execute_trade(signal, size)

            self.calibration_records = cal_store.add_record(self.calibration_records, {
                "market_id": market.id,
                "market_title": market.title,
                "team_a": market.team_a,
                "team_b": market.team_b,
                "predicted_prob": model_prob,
                "market_prob": market_prob,
                "edge": edge,
                "confidence": conf,
                "outcome": None,
                "pnl": None,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })

        except Exception as e:
            logger.error(f"Error processing market {market.title}: {e}", exc_info=True)

    def resolve_expired_markets(self) -> None:
        logger.info("=== Resolving expired markets ===")
        open_trades = self.paper_trader.get_open_trades()
        now = datetime.now(timezone.utc)
        resolved = 0

        for trade in open_trades:
            res_date_str = trade.get("resolution_date", "")
            try:
                from dateutil import parser as dp
                res_date = dp.parse(res_date_str)
                if res_date.tzinfo is None:
                    res_date = res_date.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            if now < res_date:
                continue

            logger.info(f"Resolving {trade['team_a']} vs {trade['team_b']} — checking result...")
            outcome = self._fetch_match_outcome(trade)
            if outcome is None:
                logger.warning(f"Could not determine outcome for {trade['market_id']}, skipping")
                continue

            result = self.paper_trader.resolve_trade(trade["market_id"], outcome)
            if result:
                self.calibration_records = cal_store.update_outcome(
                    self.calibration_records, trade["market_id"], outcome, result["pnl"]
                )
                resolved += 1

        logger.info(f"Resolved {resolved} expired markets")

    def _fetch_match_outcome(self, trade: dict) -> bool | None:
        """Try to resolve outcome from Cito API or Oracle's Elixir cache."""
        team_a = trade.get("team_a", "")
        team_b = trade.get("team_b", "")

        if self._match_df is not None and not self._match_df.empty:
            res_str = trade.get("resolution_date", "")
            try:
                from dateutil import parser as dp
                res_date = dp.parse(res_str).date()
            except Exception:
                return None

            recent = self._match_df[self._match_df["date"].dt.date == res_date]
            a_rows = recent[recent["teamname"] == team_a]
            if not a_rows.empty:
                return bool(a_rows.iloc[0]["result"] == 1)

        return None

    def export_report(self) -> None:
        export_report(self.paper_trader)

    def print_status(self) -> None:
        summary = self.paper_trader.get_pnl_summary()
        log_status(
            self.paper_trader.capital,
            self.paper_trader.get_portfolio_value(),
            len(self.paper_trader.get_open_trades()),
            summary,
        )
