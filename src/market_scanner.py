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
# "sports" tag floods results with soccer — only use esports-specific slugs
TAG_SLUGS = ["esports", "league-of-legends"]

# Polymarket LoL match format: "LoL: TeamA vs TeamB (BOX) - Context"
LOL_MATCH_RE = re.compile(
    r"^LoL:\s+(.+?)\s+vs\s+(.+?)\s+\(BO\d\)",
    re.IGNORECASE,
)

# Normalise Polymarket team names → canonical names used in team_ratings.json
TEAM_ALIASES: dict[str, str] = {
    # LCK
    "BNK FEARX": "BNK FearX",
    "Nongshim Red Force": "Nongshim RedForce",
    "Kiwoom DRX": "DRX",
    "HANJIN BRION": "BNK FearX",   # rebranded from OKSavingsBank BRION
    "Hanwha Life Esports": "HLE",
    "KT Rolster": "KT",
    "DN SOOPers": "DN SOOPers",
    # LEC
    "Movistar KOI": "MAD Lions KOI",  # formerly MAD Lions
    "G2 NORD": "G2",
    "Shifters": "Fnatic",             # Fnatic academy
    "Eintracht Spandau": "Eintracht Spandau",
    # LCS
    "LYON": "LYON",
    "Shopify Rebellion": "Shopify Rebellion",
    "Disguised": "Disguised",
    # LPL
    "Invictus Gaming": "Invictus Gaming",
    "ThunderTalk Gaming": "ThunderTalk Gaming",
    "LGD Gaming": "LGD Gaming",
    "LNG Esports": "LNG Esports",
    "Anyone's Legend": "Anyone's Legend",
    "Team WE": "Team WE",
    "Oh My God": "Oh My God",
    "Bilibili Gaming": "BLG",
    "Top Esports": "TES",
    "JD Gaming": "JDG",
    "Weibo Gaming": "WBG",
    "EDward Gaming": "EDG",
    # Misc
    "Ninjas in Pyjamas": "NiP",
    "Cloud9": "C9",
    "Team Liquid": "TL",
    "G2 Esports": "G2",
    "Karmine Corp": "KC",
    "Team Vitality": "Vitality",
    "SK Gaming": "SK",
    "Fnatic": "FNC",
    "FlyQuest": "FlyQuest",
    "Dignitas": "DIG",
    "Gen.G": "Gen.G",
    "Dplus KIA": "DK",
    "T1": "T1",
}


def normalise_team(name: str) -> str:
    """Map a Polymarket team name to the canonical name in team_ratings.json."""
    return TEAM_ALIASES.get(name, name)


def _detect_region(context: str) -> str:
    ctx = context.upper()
    if "LCK" in ctx:
        return "LCK"
    if "LEC" in ctx or "EMEA" in ctx or "EUROPE" in ctx:
        return "LEC"
    if "LCS" in ctx or "NORTH AMERICA" in ctx:
        return "LCS"
    if "LPL" in ctx or "CHINA" in ctx:
        return "LPL"
    if "LIT" in ctx or "VCS" in ctx:
        return "Other"
    return "Unknown"


def _parse_prices(market: dict) -> tuple[float, float]:
    try:
        prices = market.get("outcomePrices", [])
        if isinstance(prices, str):
            import json
            prices = json.loads(prices)
        if isinstance(prices, list) and len(prices) >= 2:
            yes_price = float(prices[0])
            no_price = float(prices[1])
            return max(0.001, min(0.999, yes_price)), max(0.001, min(0.999, no_price))
        outcomes = market.get("outcomes", [])
        if isinstance(outcomes, list) and len(outcomes) >= 2:
            for o in outcomes:
                if isinstance(o, dict) and o.get("name", "").upper() in ("YES", "WIN", "1"):
                    p = float(o.get("price", 0.5))
                    return max(0.001, min(0.999, p)), max(0.001, min(0.999, 1 - p))
    except Exception:
        pass
    return 0.5, 0.5


def _parse_resolution_date(obj: dict) -> Optional[datetime]:
    for key in ("endDate", "resolutionDate", "end_date", "resolution_date"):
        val = obj.get(key)
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

        # Only process events whose title starts with "LoL:" — the format Polymarket uses
        m = LOL_MATCH_RE.match(title)
        if not m:
            continue

        raw_team_a = m.group(1).strip()
        raw_team_b = m.group(2).strip()
        team_a = normalise_team(raw_team_a)
        team_b = normalise_team(raw_team_b)

        # Detect region from the context after " - "
        context = title.split(" - ", 1)[1] if " - " in title else ""
        region = _detect_region(context)

        sub_markets = event.get("markets", [event])
        for mkt in sub_markets:
            yes_price, no_price = _parse_prices(mkt)
            spread = abs(yes_price + no_price - 1.0)
            liquidity = float(mkt.get("liquidity", event.get("liquidity", 0)) or 0)
            volume = float(mkt.get("volume", event.get("volume", 0)) or 0)
            resolution_date = _parse_resolution_date(mkt) or _parse_resolution_date(event)

            if resolution_date is None:
                continue

            market_id = str(mkt.get("id", event.get("id", "")))
            question = mkt.get("question", mkt.get("title", title))

            markets.append(MatchMarket(
                id=market_id,
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
                question=question,
                slug=event.get("slug", ""),
                active=not event.get("closed", False),
            ))

    logger.info(f"Parsed {len(markets)} LoL match markets")
    return markets
