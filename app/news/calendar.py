"""News / economic-calendar filter.

Blocks NEW entries inside a window around high-impact events (CPI, FOMC, NFP,
rate decisions) and major crypto events (ETF, regulation, exchange incidents).
Volatility around these is unpredictable and spreads blow out — a great way to
get stopped on noise.

MVP ships an in-memory event list + interface. Wire a real source later (e.g.
ForexFactory / Trading Economics for macro, an exchange status feed for crypto)
by populating ``events`` or loading from the ``events`` DB table.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class Event:
    ts: datetime
    kind: str       # cpi|fomc|nfp|rate|etf|reg|exchange
    impact: str     # low|med|high
    title: str


class NewsFilter:
    def __init__(self, events: list[Event] | None = None,
                 block_before: timedelta = timedelta(minutes=30),
                 block_after: timedelta = timedelta(minutes=30)):
        self.events = events or []
        self.block_before = block_before
        self.block_after = block_after

    def is_blocked(self, now: datetime | None = None) -> tuple[bool, str | None]:
        now = now or datetime.now(timezone.utc)
        for e in self.events:
            if e.impact != "high":
                continue
            if e.ts - self.block_before <= now <= e.ts + self.block_after:
                return True, f"high-impact {e.kind}: {e.title}"
        return False, None
