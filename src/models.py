from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict


class TradeAction(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    NO_TRADE = "NO_TRADE"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class MatchMarket(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    title: str
    team_a: str
    team_b: str
    region: str                       # LCK, LEC, LCS, LPL
    yes_price: float                  # P(YES) from market
    no_price: float
    liquidity: float
    volume: float
    spread: float
    resolution_date: datetime
    question: str
    slug: str
    active: bool = True


class TeamStats(BaseModel):
    name: str
    elo: float = 1500.0
    games_played: int = 0
    wins: int = 0
    recent_results: list[int] = field(default_factory=list)  # 1=win, 0=loss, newest first

    @property
    def win_rate(self) -> float:
        if self.games_played == 0:
            return 0.5
        return self.wins / self.games_played


class MatchPrediction(BaseModel):
    team_a: str
    team_b: str
    p_a_wins: float           # our model's probability that team_a wins
    p_elo: float
    p_form: float
    p_h2h: float
    elo_a: float
    elo_b: float
    team_a_matches: int
    team_b_matches: int
    confidence: float         # 0–100


class TradeSignal(BaseModel):
    action: TradeAction
    market: MatchMarket
    prediction: MatchPrediction
    model_probability: float   # our P(YES)
    market_probability: float  # market's P(YES)
    edge: float                # model_prob - market_prob
    kelly_size: float
    recommended_size: float
    confidence: float
    rejection_reasons: list[str] = []


class Trade(BaseModel):
    id: str
    signal: TradeSignal
    fill_price: float
    size: float
    status: TradeStatus = TradeStatus.OPEN
    opened_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    outcome: Optional[bool] = None    # True = win
    pnl: Optional[float] = None


class CalibrationRecord(BaseModel):
    market_id: str
    predicted_prob: float
    market_prob: float
    edge: float
    confidence: float
    outcome: Optional[bool] = None
    pnl: Optional[float] = None
    recorded_at: datetime = field(default_factory=datetime.utcnow)
