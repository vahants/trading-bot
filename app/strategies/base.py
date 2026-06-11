"""Strategy interface.

A strategy is a PURE decision function: given a DataFrame of candles (with
indicators) up to the current bar, it returns a Signal or None. It does NOT size
positions, place orders, or know about the account — that separation is what lets
the same code run in backtest, paper and live, and keeps risk authority in one
place (the RiskManager).

HARD RULE: a Signal MUST include a stop. No stop, no trade.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

import pandas as pd

from app.db.models import Side


@dataclass
class Signal:
    side: Side
    entry: float
    stop: float                       # mandatory
    take_profit: float | None = None
    trailing_atr_mult: float | None = None  # trail distance in ATRs once in profit
    family: str = "trend"             # which regime-permission group this belongs to
    reason: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        # Defensive: a stop on the wrong side of entry is a bug that would flip
        # risk sizing. Catch it loudly at construction time.
        if self.side == Side.long and self.stop >= self.entry:
            raise ValueError("long stop must be below entry")
        if self.side == Side.short and self.stop <= self.entry:
            raise ValueError("short stop must be above entry")

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)


class Strategy(abc.ABC):
    name: str = "base"
    family: str = "trend"

    @abc.abstractmethod
    def generate(self, df: pd.DataFrame) -> Signal | None:
        """Return a Signal for the LAST bar of `df`, or None for no trade."""
        ...
