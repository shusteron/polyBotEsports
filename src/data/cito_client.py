"""Cito API client for live LoL esports data (free tier, 500 req/month)."""
from __future__ import annotations

import os
import time
from typing import Optional

import requests
from loguru import logger

BASE_URL = "https://api.cito.gg/api/v1/lol"
REQUEST_DELAY = 1.0  # seconds between calls — preserve free-tier quota


class CitoClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("CITO_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        url = f"{BASE_URL}{path}"
        try:
            r = self.session.get(url, params=params, timeout=15)
            time.sleep(REQUEST_DELAY)
            if r.status_code == 401:
                logger.warning("Cito API: unauthorized — check CITO_API_KEY")
                return None
            if r.status_code == 429:
                logger.warning("Cito API: rate limit hit, sleeping 60s")
                time.sleep(60)
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Cito API error [{path}]: {e}")
            return None

    def get_schedule_today(self) -> list[dict]:
        data = self._get("/schedule/today")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("matches", data.get("data", []))
        return []

    def get_schedule_upcoming(self) -> list[dict]:
        data = self._get("/schedule/upcoming")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("matches", data.get("data", []))
        return []

    def get_team_stats(self, team_name: str) -> dict | None:
        data = self._get("/teams", params={"name": team_name})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None

    def get_head_to_head(self, team_a: str, team_b: str) -> dict | None:
        data = self._get("/h2h", params={"team1": team_a, "team2": team_b})
        if isinstance(data, dict):
            return data
        return None

    def available(self) -> bool:
        return bool(self.api_key)
