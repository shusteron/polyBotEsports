"""Tracks historical prediction accuracy for calibration scoring."""
from __future__ import annotations

import json
from pathlib import Path

CALIBRATION_PATH = Path("data/calibration.json")


def load_calibration() -> list[dict]:
    if not CALIBRATION_PATH.exists():
        return []
    with open(CALIBRATION_PATH) as f:
        return json.load(f)


def save_calibration(records: list[dict]) -> None:
    CALIBRATION_PATH.parent.mkdir(exist_ok=True)
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(records, f, indent=2)


def get_accuracy(records: list[dict], min_records: int = 5) -> float:
    """Fraction of resolved trades where prediction direction was correct."""
    resolved = [r for r in records if r.get("outcome") is not None]
    if len(resolved) < min_records:
        return 0.5  # neutral default before enough history
    correct = sum(
        1 for r in resolved
        if (r["predicted_prob"] >= 0.5) == bool(r["outcome"])
    )
    return correct / len(resolved)


def add_record(records: list[dict], entry: dict) -> list[dict]:
    records.append(entry)
    save_calibration(records)
    return records


def update_outcome(records: list[dict], market_id: str, outcome: bool, pnl: float) -> list[dict]:
    for r in records:
        if r.get("market_id") == market_id and r.get("outcome") is None:
            r["outcome"] = outcome
            r["pnl"] = pnl
            break
    save_calibration(records)
    return records
