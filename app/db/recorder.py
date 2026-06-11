"""Best-effort persistence of signals/trades/equity to PostgreSQL.

Designed to NEVER crash the trading loop: if the DB is unreachable, every method
swallows the error (the engine also wraps these in try/except). That means you can
run paper trading with zero infrastructure, and turn on Postgres later for history
and the dashboard without touching strategy code.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

log = logging.getLogger("recorder")


class Recorder:
    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self._ok = False
        try:
            from app.db.base import init_db
            init_db()
            self._ok = True
        except Exception as e:  # no DB -> degrade silently to no-op
            log.warning("Recorder disabled (no DB): %s", e)

    def _session(self):
        from app.db.base import get_session_factory
        return get_session_factory()()

    def save_signal(self, symbol, signal, regime, assessment, timeframe) -> None:
        if not self._ok:
            return
        from app.db.models import SignalRow, Mode
        with self._session() as s:
            s.add(SignalRow(
                symbol=symbol, strategy="engine", side=signal.side,
                timeframe=timeframe, entry=signal.entry, stop=signal.stop,
                take_profit=signal.take_profit, regime=regime,
                ai_score=assessment.score, ai_reason=assessment.summary,
                risk_passed=assessment.allow,
            ))
            s.commit()

    def save_trade(self, t: dict) -> None:
        if not self._ok:
            return
        from app.db.models import Trade, Side, Mode
        with self._session() as s:
            s.add(Trade(
                symbol=t["symbol"], strategy=t["strategy"],
                side=Side(t["side"]), mode=Mode(t["mode"]),
                open_ts=t["open_ts"], close_ts=t["close_ts"],
                entry_price=t["entry_price"], exit_price=t["exit_price"],
                qty=t["qty"], net_pnl=t["net_pnl"], r_multiple=t.get("r_multiple"),
                stop=t["stop"], take_profit=t.get("take_profit"),
                exit_reason=t["exit_reason"],
            ))
            s.commit()

    def save_equity(self, equity: float, balance: float, open_positions: int,
                    daily_pnl: float, drawdown: float) -> None:
        if not self._ok:
            return
        from app.db.models import EquitySnapshot, Mode
        with self._session() as s:
            s.add(EquitySnapshot(
                mode=Mode(self.mode), balance=balance, equity=equity,
                open_positions=open_positions, daily_pnl=daily_pnl,
                drawdown=drawdown,
            ))
            s.commit()
