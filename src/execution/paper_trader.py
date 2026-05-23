"""Simulated paper trading engine — identical pattern to weather bot."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.models import Trade, TradeAction, TradeStatus

STATE_PATH = Path("data/paper_trades.json")


class PaperTrader:
    def __init__(self, starting_capital: float = 10000.0, slippage: float = 0.002, fee: float = 0.002):
        self.starting_capital = starting_capital
        self.slippage = slippage
        self.fee = fee
        self._state = self._load()

    def _load(self) -> dict:
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                return json.load(f)
        return {"capital": self.starting_capital, "trades": []}

    def _save(self) -> None:
        STATE_PATH.parent.mkdir(exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    @property
    def capital(self) -> float:
        return self._state["capital"]

    def execute_trade(self, signal, size: float) -> Optional[Trade]:
        if signal.action == TradeAction.NO_TRADE:
            return None
        base_price = signal.market_probability
        fill_price = min(0.999, base_price * (1 + self.slippage) + self.fee)
        cost = size

        if cost > self.capital:
            logger.warning(f"Insufficient capital: need ${cost:.2f}, have ${self.capital:.2f}")
            return None

        self._state["capital"] -= cost
        trade_id = str(uuid.uuid4())[:8]
        trade_data = {
            "id": trade_id,
            "market_id": signal.market.id,
            "market_title": signal.market.title,
            "team_a": signal.market.team_a,
            "team_b": signal.market.team_b,
            "action": signal.action.value,
            "fill_price": fill_price,
            "size": size,
            "model_prob": signal.model_probability,
            "market_prob": signal.market_probability,
            "edge": signal.edge,
            "confidence": signal.confidence,
            "status": TradeStatus.OPEN.value,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "resolution_date": signal.market.resolution_date.isoformat(),
            "pnl": None,
            "outcome": None,
        }
        self._state["trades"].append(trade_data)
        self._save()
        logger.info(
            f"PAPER TRADE | {signal.action.value} ${size:.2f} @ {fill_price:.3f} | "
            f"{signal.market.team_a} vs {signal.market.team_b} | edge={signal.edge:.3f}"
        )
        return trade_data

    def resolve_trade(self, market_id: str, outcome_yes: bool) -> Optional[dict]:
        for t in self._state["trades"]:
            if t["market_id"] == market_id and t["status"] == TradeStatus.OPEN.value:
                action = t["action"]
                size = t["size"]
                fill = t["fill_price"]

                win = (action == TradeAction.BUY_YES.value and outcome_yes) or \
                      (action == TradeAction.BUY_NO.value and not outcome_yes)

                payout = (size / fill) if win else 0.0
                pnl = payout - size

                t["status"] = TradeStatus.RESOLVED.value
                t["outcome"] = outcome_yes
                t["pnl"] = pnl
                t["resolved_at"] = datetime.now(timezone.utc).isoformat()
                self._state["capital"] += payout
                self._save()
                logger.info(f"RESOLVED | {market_id} | {'WIN' if win else 'LOSS'} | PnL ${pnl:+.2f}")
                return t
        return None

    def get_open_trades(self) -> list[dict]:
        return [t for t in self._state["trades"] if t["status"] == TradeStatus.OPEN.value]

    def get_pnl_summary(self) -> dict:
        resolved = [t for t in self._state["trades"] if t["status"] == TradeStatus.RESOLVED.value]
        if not resolved:
            return {"total_pnl": 0.0, "win_rate": 0.0, "n_trades": 0, "avg_edge": 0.0}
        wins = [t for t in resolved if t.get("pnl", 0) > 0]
        return {
            "total_pnl": sum(t["pnl"] for t in resolved),
            "win_rate": len(wins) / len(resolved),
            "n_trades": len(resolved),
            "avg_edge": sum(t["edge"] for t in resolved) / len(resolved),
        }

    def get_portfolio_value(self) -> float:
        open_value = sum(t["size"] for t in self.get_open_trades())
        return self.capital + open_value
