"""Scans Polymarket Gamma API for LoL esports match-winner markets."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import requests
from dateutil import parser as dateutil_parser
from loguru import logger

from src.models import MatchMarket

GAMMA_API = "https://gamma-api.polymarket.com"
PAGE_SIZE = 100
TAG_SLUGS = ["esports", "league-of-legends", "sports"]

# Known LoL team names (LCK + LEC focus, plus Worlds-level teams)
LOL_TEAMS = {
    # LCK
    "T1", "Gen.G", "KT Rolster", "KT", "Hanwha Life", "HLE", "DRX",
    "BNK FearX", "FearX", "OKSavingsBank BRION", "BRION", "Dplus KIA", "DK",
    "Nongshim RedForce", "Nongshim",
    # LEC
    "G2 Esports", "G2", "Fnatic", "FNC", "Team Vitality", "Vitality",
    "MAD Lions KOI", "MAD Lions", "MAD", "Karmine Corp", "KC",
    "Team BDS", "BDS", "SK Gaming", "SK", "Rogue", "NaVi", "NAVI",
    # LCS (bonus)
    "Cloud9", "C9", "Team Liquid", "TL", "100 Thieves", "100T",
    "FlyQuest", "NRG", "Dignitas", "DIG",
    # LPL (bonus)
    "JDG", "BLG", "EDG", "RNG", "Weibo Gaming", "WBG", "TopEsports", "TES",
    # International keywords
    "LCK", "LEC", "LCS", "LPL", "League of Legends", "LoL",
}

EXCLUDE_PATTERNS = re.compile(
    r"\b(earthquake|hurricane|tornado|flood|wildfire|volcano|pandemic|"
    r"bitcoin|crypto|election|nba|nfl|mlb|nhl|soccer|football|"
    r"world cup|cricket|tennis|golf)\b",
    re.IGNORECASE,
)

# Extract two team names from a market title like "Will T1 beat Gen.G?"
MATCH_TITLE_PATTERNS = [
    re.compile(r"Will\s+(.+?)\s+(?:beat|defeat|win against|vs\.?)\s+(.+?)[\?$]", re.IGNORECASE),
    re.compile(r"(.+?)\s+vs\.?\s+(.+?)[\?$]", re.IGNORECASE),
    re.compile(r"(.+?)\s+(?:beat|defeat|win against)\s+(.+?)[\?$]", re.IGNORECASE),
]


def _parse_teams(title: str) -> tuple[str, str] | None:
    for pattern in MATCH_TITLE_PATTERNS:
        m = pattern.search(title)
        if m:
            a = m.group(1).strip().rstrip("?").strip()
            b = m.group(2).strip().rstrip("?").strip()
            if a and b and a != b:
                return a, b
    return None


def _is_lol_market(title: str, description: str = "") -> bool:
    text = f"{title} {description}"
    if EXCLUDE_PATTERNS.search(text):
        return False
    return any(team.lower() in text.lower() for team in LOL_TEAMS)


def _detect_region(title: str) -> str:
    t = title.upper()
    if "LCK" in t:
        return "LCK"
    if "LEC" in t:
        return "LEC"
    if "LCS" in t:
        return "LCS"
    if "LPL" in t:
        return "LPL"
    return "Unknown"


def _parse_prices(market: dict) -> tuple[float, float]:
    try:
        outcomes = market.get("outcomes", [])
        prices = market.get("outcomePrices", [])
        if isinstance(prices, str):
            import json
            prices = json.loads(prices)
        if isinstance(prices, list) and len(prices) >= 2:
            yes_price = float(prices[0])
            no_price = float(prices[1])
            return max(0.001, min(0.999, yes_price)), max(0.001, min(0.999, no_price))
        if isinstance(outcomes, list) and len(outcomes) >= 2:
            for o in outcomes:
                if isinstance(o, dict) and o.get("name", "").upper() in ("YES", "WIN", "1"):
                    p = float(o.get("price", 0.5))
                    return max(0.001, min(0.999, p)), max(0.001, min(0.999, 1 - p))
    except Exception:
        pass
    return 0.5, 0.5


def _parse_resolution_date(market: dict) -> Optional[datetime]:
    for key in ("endDate", "resolutionDate", "end_date", "resolution_date"):
        val = market.get(key)
        if val:
            try:
                dt = dateutil_parser.parse(str(val))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def _fetch_events(tag_slug: str) -> list[dict]:
    events = []
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{GAMMA_API}/events",
                params={"tag_slug": tag_slug, "closed": "false", "limit": PAGE_SIZE, "offset": offset},
                timeout=20,
            )
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            events.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        except Exception as e:
            logger.warning(f"Error fetching events [{tag_slug} offset={offset}]: {e}")
            break
    return events


def scan_lol_markets() -> list[MatchMarket]:
    all_events: dict[str, dict] = {}
    for slug in TAG_SLUGS:
        for event in _fetch_events(slug):
            eid = event.get("id", "")
            if eid:
                all_events[eid] = event

    logger.info(f"Found {len(all_events)} unique events across esports tags")

    markets: list[MatchMarket] = []
    for event in all_events.values():
        title = event.get("title", "")
        description = event.get("description", "")

        if not _is_lol_market(title, description):
            continue

        # Each event may contain sub-markets; prefer the event-level binary market
        sub_markets = event.get("markets", [event])
        for mkt in sub_markets:
            mkt_title = mkt.get("question", mkt.get("title", title))
            yes_price, no_price = _parse_prices(mkt)
            spread = abs(yes_price + no_price - 1.0)
            liquidity = float(mkt.get("liquidity", event.get("liquidity", 0)) or 0)
            volume = float(mkt.get("volume", event.get("volume", 0)) or 0)
            resolution_date = _parse_resolution_date(mkt) or _parse_resolution_date(event)

            if resolution_date is None:
                continue

            teams = _parse_teams(mkt_title) or _parse_teams(title)
            if not teams:
                continue
            team_a, team_b = teams

            region = _detect_region(title) or _detect_region(mkt_title)
            market_id = mkt.get("id", event.get("id", ""))

            markets.append(MatchMarket(
                id=str(market_id),
                title=title,
                team_a=team_a,
                team_b=team_b,
                region=region,
                yes_price=yes_price,
                no_price=no_price,
                liquidity=liquidity,
                volume=volume,
                spread=spread,
                resolution_date=resolution_date,
                question=mkt_title,
                slug=event.get("slug", ""),
                active=not event.get("closed", False),
            ))

    logger.info(f"Parsed {len(markets)} LoL match markets")
    return markets
