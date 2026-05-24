"""
Force-refresh team ELO ratings from Leaguepedia.
Run manually or via CI:  python scripts/refresh_ratings.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from src.data.oracle_elixir import CACHE_PATH, _fetch_all_games, _rows_to_dataframe
from src.data.elo_engine import build_ratings, save_ratings, RATINGS_PATH


def main() -> None:
    logger.info("=== Force-refreshing team ratings from Leaguepedia ===")

    # Delete stale cache so _fetch_all_games hits the API
    if CACHE_PATH.exists():
        backup = CACHE_PATH.with_suffix(f".{datetime.utcnow().strftime('%Y%m%d_%H%M')}.bak.json")
        shutil.copy(CACHE_PATH, backup)
        CACHE_PATH.unlink()
        logger.info(f"Removed stale cache (backup: {backup.name})")

    raw_rows = _fetch_all_games()
    if not raw_rows:
        logger.error("No data fetched from Leaguepedia — aborting to protect existing ratings")
        sys.exit(1)

    # Save fresh cache
    CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(raw_rows, f)
    logger.info(f"Saved {len(raw_rows)} game rows to cache")

    df = _rows_to_dataframe(raw_rows)
    if df.empty:
        logger.error("DataFrame is empty after parsing — aborting")
        sys.exit(1)

    logger.info(f"Parsed {len(df)} team-game rows covering {df['teamname'].nunique()} teams")

    ratings = build_ratings(df)
    save_ratings(ratings)

    # Print top 15 by ELO for a quick sanity check
    sorted_teams = sorted(ratings.items(), key=lambda x: x[1]["elo"], reverse=True)
    logger.info("Top 15 teams by ELO after refresh:")
    for rank, (team, data) in enumerate(sorted_teams[:15], 1):
        logger.info(f"  #{rank:>2} {team:<30} ELO={data['elo']:.0f}  games={data['games']}  "
                    f"wins={data['wins']}  form={''.join(str(r) for r in data['recent'][:5])}")

    logger.info(f"=== Done — {len(ratings)} teams saved to {RATINGS_PATH} ===")


if __name__ == "__main__":
    main()
