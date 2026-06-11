"""End-to-end engine test with a controllable data feed (no network, no DB).

Verifies the wiring that makes "it actually trades": a signal flows through the
pipeline to OPEN a position, then price movement drives manage_open_positions to
CLOSE it on the stop, updating PnL and the consecutive-loss counter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from app.db.models import Side
from app.exchanges.base import Candle, SymbolInfo
from app.exchanges.paper import PaperExchange
from app.strategies.base import Signal, Strategy
from app.trading.engine import TradingEngine


class _DummyData:
    """A read-only 'exchange' that serves a clean uptrend so regime == trend_up."""
    def __init__(self):
        n = 300
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        prices = np.linspace(100, 200, n)
        self._candles = [
            Candle(open_time=base + timedelta(hours=i), open=float(p), high=float(p) + 0.5,
                   low=float(p) - 0.5, close=float(p), volume=120.0)
            for i, p in enumerate(prices)
        ]
        self.price = 200.0

    def get_candles(self, symbol, timeframe, limit=500):
        return self._candles[-limit:]

    def get_last_price(self, symbol):
        return self.price

    def get_symbol_info(self, symbol):
        return SymbolInfo(symbol, tick_size=0.1, qty_step=0.001, min_notional=5.0)


class _StubStrategy(Strategy):
    """Always proposes a long with a stop just below price — to exercise wiring."""
    name = "stub"
    family = "trend"

    def generate(self, df):
        price = float(df["close"].iloc[-1])
        return Signal(side=Side.long, entry=price, stop=price - 5,
                      take_profit=price + 10, trailing_atr_mult=None,
                      family="trend", reason="stub long", meta={"atr": 1.0})


def _engine():
    dummy = _DummyData()
    paper = PaperExchange(data_source=dummy, starting_equity=10_000.0)
    eng = TradingEngine(exchange=paper, strategy=_StubStrategy(), timeframe="1h")
    return eng, dummy


def test_pipeline_opens_position():
    eng, dummy = _engine()
    res = eng.process_symbol("BTCUSDT")
    assert res["action"] == "entered", res
    assert "BTCUSDT" in eng.state.open_positions
    pos = eng.state.open_positions["BTCUSDT"]
    assert pos["side"] == Side.long and pos["qty"] > 0


def test_manage_closes_on_stop_and_counts_loss():
    eng, dummy = _engine()
    eng.process_symbol("BTCUSDT")
    assert "BTCUSDT" in eng.state.open_positions

    # price falls through the stop -> should close as a loss
    dummy.price = 190.0
    events = eng.manage_open_positions()
    assert "BTCUSDT" not in eng.state.open_positions
    assert events and events[0]["reason"] == "stop"
    assert events[0]["pnl"] < 0
    assert eng.state.consecutive_losses == 1
    assert len(eng.state.trades) == 1


def test_take_profit_closes_as_win():
    eng, dummy = _engine()
    eng.process_symbol("BTCUSDT")
    dummy.price = 215.0  # above take_profit
    events = eng.manage_open_positions()
    assert events and events[0]["reason"] == "take_profit"
    assert events[0]["pnl"] > 0
    assert eng.state.consecutive_losses == 0


def test_kill_switch_flattens_and_halts():
    eng, dummy = _engine()
    eng.process_symbol("BTCUSDT")
    eng.kill(flatten=True)
    assert eng.state.open_positions == {}
    assert eng.state.halted and eng.state.halt_reason == "manual kill switch"


# ---- robustness fixes (retry-storm / overtrading / unprotected position) ----

class _RejectingExchange(PaperExchange):
    """Simulates Bybit rejecting every order (e.g. the 10024 regulatory error)."""
    def place_order(self, req):
        raise RuntimeError("regulatory restriction (ErrCode: 10024)")


class _StopFailExchange(PaperExchange):
    """Entry succeeds, but the protective stop is rejected."""
    supports_resting_stops = True

    def place_order(self, req):
        if req.reduce_only and req.stop_price is not None:
            raise RuntimeError("stop order rejected")
        return super().place_order(req)


def test_rejected_entry_does_not_crash_or_open_and_sets_cooldown():
    dummy = _DummyData()
    ex = _RejectingExchange(data_source=dummy, starting_equity=10_000.0)
    eng = TradingEngine(exchange=ex, strategy=_StubStrategy(), timeframe="1h")
    res = eng.process_symbol("BTCUSDT")          # must NOT raise
    assert res["action"] == "rejected"
    assert "BTCUSDT" not in eng.state.open_positions      # nothing opened
    assert "BTCUSDT" in eng.state.entry_cooldown_until    # cooldown armed


def test_no_duplicate_entry_on_same_candle():
    eng, dummy = _engine()
    assert eng.process_symbol("BTCUSDT")["action"] == "entered"
    # close it so the "position already open" guard isn't what stops re-entry
    dummy.price = 190.0
    eng.manage_open_positions()
    assert "BTCUSDT" not in eng.state.open_positions
    # same candle -> must be gated, NOT re-entered
    res = eng.process_symbol("BTCUSDT")
    assert res["action"] == "none"
    assert "already evaluated this candle" in res["reason"]


class _PermanentBlockExchange(PaperExchange):
    """Simulates a fatal Bybit rejection (e.g. 10024 regulatory restriction)."""
    def place_order(self, req):
        from app.exchanges.base import PermanentOrderError
        raise PermanentOrderError("regulatory restriction (ErrCode: 10024)")


def test_permanent_block_stops_bot_cleanly():
    dummy = _DummyData()
    ex = _PermanentBlockExchange(data_source=dummy, starting_equity=10_000.0)
    eng = TradingEngine(exchange=ex, strategy=_StubStrategy(), timeframe="1h")
    eng.state.running = True
    res = eng.process_symbol("BTCUSDT")          # must NOT raise
    assert res["action"] == "rejected"
    assert eng.state.running is False            # bot stopped itself
    assert eng.state.halted and "blocked orders" in eng.state.halt_reason
    assert "BTCUSDT" not in eng.state.open_positions


def test_stop_failure_closes_position_immediately():
    dummy = _DummyData()
    ex = _StopFailExchange(data_source=dummy, starting_equity=10_000.0)
    eng = TradingEngine(exchange=ex, strategy=_StubStrategy(), timeframe="1h")
    res = eng.process_symbol("BTCUSDT")
    # entry filled but stop rejected -> position must be auto-closed, not left open
    assert "BTCUSDT" not in eng.state.open_positions
    assert res["action"] == "rejected"
    assert eng.state.trades and eng.state.trades[-1]["exit_reason"] == "stop_place_failed"
