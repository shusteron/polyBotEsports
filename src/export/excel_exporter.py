"""Excel report generator — same pattern as weather bot."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

EXPORT_PATH = Path("exports/esports_report.xlsx")


def export_report(paper_trader) -> None:
    EXPORT_PATH.parent.mkdir(exist_ok=True)
    trades = paper_trader._state.get("trades", [])
    summary = paper_trader.get_pnl_summary()

    df_trades = pd.DataFrame(trades) if trades else pd.DataFrame(
        columns=["id", "market_title", "team_a", "team_b", "action", "fill_price",
                 "size", "model_prob", "market_prob", "edge", "confidence",
                 "status", "opened_at", "resolution_date", "pnl", "outcome"]
    )

    summary_data = {
        "Metric": ["Capital", "Portfolio Value", "Total PnL", "Win Rate", "Total Trades", "Open Positions"],
        "Value": [
            f"${paper_trader.capital:.2f}",
            f"${paper_trader.get_portfolio_value():.2f}",
            f"${summary['total_pnl']:.2f}",
            f"{summary['win_rate']:.1%}",
            summary["n_trades"],
            len(paper_trader.get_open_trades()),
        ],
    }
    df_summary = pd.DataFrame(summary_data)

    with pd.ExcelWriter(EXPORT_PATH, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Summary", index=False)
        df_trades.to_excel(writer, sheet_name="All Trades", index=False)

    logger.info(f"Excel report exported to {EXPORT_PATH}")
