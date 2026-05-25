"""Excel report generator."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

EXPORT_PATH = Path("exports/esports_report.xlsx")


def _human_action(trade: dict) -> str:
    """Convert BUY_YES/BUY_NO into readable bet description."""
    action = trade.get("action", "")
    team_a = trade.get("team_a", "?")
    team_b = trade.get("team_b", "?")
    if action == "BUY_YES":
        return f"Bet {team_a} to win"
    if action == "BUY_NO":
        return f"Bet {team_b} to win"
    return action


def _outcome_label(trade: dict) -> str:
    outcome = trade.get("outcome")
    action = trade.get("action", "")
    team_a = trade.get("team_a", "?")
    team_b = trade.get("team_b", "?")
    if outcome is None:
        return "Pending"
    winner = team_a if outcome else team_b
    bet_won = (action == "BUY_YES" and outcome) or (action == "BUY_NO" and not outcome)
    return f"{'WIN' if bet_won else 'LOSS'} — {winner} won"


def export_report(paper_trader) -> None:
    EXPORT_PATH.parent.mkdir(exist_ok=True)
    trades = paper_trader._state.get("trades", [])
    summary = paper_trader.get_pnl_summary()

    rows = []
    for t in trades:
        rows.append({
            "Match": f"{t.get('team_a')} vs {t.get('team_b')}",
            "Tournament": t.get("market_title", ""),
            "Bet": _human_action(t),
            "Size ($)": t.get("size"),
            "Fill Price": round(t.get("fill_price", 0), 4),
            "Model Prob": f"{t.get('model_prob', 0):.1%}",
            "Market Prob": f"{t.get('market_prob', 0):.1%}",
            "Edge": f"{t.get('edge', 0):+.1%}",
            "Confidence": t.get("confidence"),
            "Status": t.get("status"),
            "Outcome": _outcome_label(t),
            "PnL ($)": round(t.get("pnl") or 0, 2) if t.get("pnl") is not None else "",
            "Opened": t.get("opened_at", "")[:16].replace("T", " "),
            "Resolves": t.get("resolution_date", "")[:16].replace("T", " "),
        })

    df_trades = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Match", "Tournament", "Bet", "Size ($)", "Fill Price",
                 "Model Prob", "Market Prob", "Edge", "Confidence",
                 "Status", "Outcome", "PnL ($)", "Opened", "Resolves"]
    )

    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    resolved_trades = [t for t in trades if t.get("status") == "RESOLVED"]
    total_pnl = sum(t.get("pnl") or 0 for t in resolved_trades)
    wins = [t for t in resolved_trades if (t.get("pnl") or 0) > 0]

    summary_data = {
        "Metric": [
            "Generated At",
            "Starting Capital",
            "Current Capital",
            "Portfolio Value",
            "Total PnL",
            "Win Rate",
            "Resolved Trades",
            "Open Positions",
            "Avg Edge (resolved)",
        ],
        "Value": [
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "$10,000.00",
            f"${paper_trader.capital:.2f}",
            f"${paper_trader.get_portfolio_value():.2f}",
            f"${total_pnl:+.2f}",
            f"{len(wins)/len(resolved_trades):.1%}" if resolved_trades else "N/A",
            len(resolved_trades),
            len(open_trades),
            f"{summary.get('avg_edge', 0):+.1%}" if resolved_trades else "N/A",
        ],
    }
    df_summary = pd.DataFrame(summary_data)

    with pd.ExcelWriter(EXPORT_PATH, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Summary", index=False)
        df_trades.to_excel(writer, sheet_name="All Trades", index=False)

        # Auto-width columns
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

    logger.info(f"Excel report exported to {EXPORT_PATH}")
