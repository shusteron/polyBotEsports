"""Kelly sizing and position limits — identical pattern to weather bot."""
from __future__ import annotations

from loguru import logger


class RiskManager:
    def __init__(self, cfg: dict):
        self.kelly_fraction = cfg["kelly_fraction"]
        self.max_trade_pct = cfg["max_trade_pct"]
        self.max_daily_pct = cfg["max_daily_pct"]
        self.max_concurrent = cfg["max_concurrent_positions"]
        self.min_size = cfg["min_trade_size"]
        self.max_size = cfg["max_trade_size"]

    def kelly_size(self, prob: float, price: float, capital: float) -> float:
        b = (1.0 / price) - 1.0  # net odds
        q = 1.0 - prob
        f_star = (prob * b - q) / b
        f_star = max(0.0, f_star)
        raw = f_star * self.kelly_fraction * capital
        capped = min(raw, self.max_trade_pct * capital, self.max_size)
        return max(0.0, capped)

    def get_approved_size(
        self,
        prob: float,
        price: float,
        capital: float,
        open_trades: list[dict],
        today_trades: list[dict],
    ) -> float:
        if len(open_trades) >= self.max_concurrent:
            logger.debug(f"Position limit reached: {len(open_trades)}/{self.max_concurrent}")
            return 0.0

        size = self.kelly_size(prob, price, capital)
        if size < self.min_size:
            return 0.0

        daily_exposure = sum(t["size"] for t in today_trades)
        if daily_exposure + size > self.max_daily_pct * capital:
            remaining = max(0.0, self.max_daily_pct * capital - daily_exposure)
            size = min(size, remaining)

        return round(size, 2) if size >= self.min_size else 0.0
