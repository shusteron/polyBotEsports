"""
Fetches professional LoL match history from Leaguepedia (lol.fandom.com MediaWiki API).
No API key needed. Replaces the original Oracle's Elixir CSV source which moved off S3.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from loguru import logger

CACHE_PATH = Path("data/match_cache.json")
CACHE_HOURS = 12

API_URL = "https://lol.fandom.com/api.php"
TARGET_LEAGUES = {"LCK", "LEC", "LCS", "LPL", "Worlds", "MSI"}
REQUEST_DELAY = 0.5  # seconds between pages


def _cache_is_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    age = time.time() - CACHE_PATH.stat().st_mtime
    return age < CACHE_HOURS * 3600


def _fetch_page(offset: int = 0, limit: int = 500) -> list[dict]:
    params = {
        "action": "cargoquery",
        "tables": "ScoreboardGames",
        "fields": "DateTime_UTC,Team1,Team2,Winner,League,Split,OverviewPage",
        # Filter only by date — league name field contains full strings like "LCK 2024 Summer"
        "where": "DateTime_UTC >= '2023-01-01' AND (League LIKE '%LCK%' OR League LIKE '%LEC%' OR League LIKE '%LCS%' OR League LIKE '%LPL%' OR League LIKE '%MSI%' OR League LIKE '%World%')",
        "order_by": "DateTime_UTC ASC",
        "limit": limit,
        "offset": offset,
        "format": "json",
    }
    try:
        r = requests.get(
            API_URL,
            params=params,
            timeout=30,
            headers={"User-Agent": "EsportsBot/1.0 (prediction bot; contact via GitHub)"},
        )
        if r.status_code == 429:
            logger.warning("Leaguepedia rate-limited, sleeping 10s")
            time.sleep(10)
            return []
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            logger.warning(f"Leaguepedia API error: {data['error']}")
            return []
        return data.get("cargoquery", [])
    except Exception as e:
        logger.warning(f"Leaguepedia fetch error [offset={offset}]: {e}")
        return []


def _fetch_all_games() -> list[dict]:
    rows = []
    offset = 0
    while True:
        page = _fetch_page(offset=offset)
        if not page:
            break
        rows.extend(page)
        logger.debug(f"Fetched {len(rows)} games so far...")
        if len(page) < 500:
            break
        offset += 500
        time.sleep(REQUEST_DELAY)
    logger.info(f"Fetched {len(rows)} total games from Leaguepedia")
    return rows


def _rows_to_dataframe(raw_rows: list[dict]) -> pd.DataFrame:
    records = []
    for entry in raw_rows:
        r = entry.get("title", {})
        team1 = r.get("Team1", "").strip()
        team2 = r.get("Team2", "").strip()
        winner = r.get("Winner", "").strip()
        date_str = r.get("DateTime UTC", r.get("DateTime_UTC", ""))
        league = r.get("League", "")

        if not team1 or not team2 or not winner:
            continue

        try:
            dt = datetime.fromisoformat(date_str.replace(" ", "T"))
        except Exception:
            continue

        # Emit two rows per game (one per team), same as Oracle's Elixir format
        records.append({
            "teamname": team1,
            "opponent": team2,
            "result": 1 if winner == team1 else 0,
            "date": dt,
            "league": league,
            "gameid": f"{team1}v{team2}_{date_str}",
            "position": "team",
        })
        records.append({
            "teamname": team2,
            "opponent": team1,
            "result": 1 if winner == team2 else 0,
            "date": dt,
            "league": league,
            "gameid": f"{team1}v{team2}_{date_str}",
            "position": "team",
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def load_match_data(cache_hours: int = CACHE_HOURS) -> pd.DataFrame:
    """Return team-level match rows for LCK, LEC, LCS, LPL."""
    if _cache_is_fresh():
        logger.info("Using cached Leaguepedia match data")
        with open(CACHE_PATH) as f:
            raw = json.load(f)
        return _rows_to_dataframe(raw)

    logger.info("Fetching match history from Leaguepedia...")
    all_rows = _fetch_all_games()

    if not all_rows:
        # Try loading stale cache rather than failing completely
        if CACHE_PATH.exists():
            logger.warning("Leaguepedia fetch failed — using stale cache")
            with open(CACHE_PATH) as f:
                raw = json.load(f)
            return _rows_to_dataframe(raw)
        return pd.DataFrame()

    CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(all_rows, f)
    logger.info(f"Cached {len(all_rows)} game entries to {CACHE_PATH}")

    return _rows_to_dataframe(all_rows)


def get_head_to_head(df: pd.DataFrame, team_a: str, team_b: str) -> dict:
    """Return H2H record between two teams."""
    if df.empty:
        return {"team_a": team_a, "team_b": team_b, "a_wins": 0, "b_wins": 0, "total": 0}

    h2h_a = df[(df["teamname"] == team_a) & (df["opponent"] == team_b)]
    h2h_b = df[(df["teamname"] == team_b) & (df["opponent"] == team_a)]

    a_wins = int(h2h_a["result"].sum())
    b_wins = int(h2h_b["result"].sum())
    return {
        "team_a": team_a,
        "team_b": team_b,
        "a_wins": a_wins,
        "b_wins": b_wins,
        "total": a_wins + b_wins,
    }
