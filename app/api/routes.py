"""REST + control API (FastAPI).

This single process can BOTH expose the dashboard API and run the trading loop in
a background thread — so `uvicorn app.main:app` + `POST /control/start` is all you
need to go from "API key entered" to "bot trading" (paper by default).

Read endpoints expose status/positions/trades/risk. Control endpoints start/stop,
switch mode, and — most importantly — the emergency KILL switch.

Secrets are never returned by any endpoint. Going live requires an explicit
confirm flag so you can't flip to real money by accident.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()


class Controller:
    """Owns the engine + the background loop thread."""
    def __init__(self):
        self.engine = None
        self.mode = get_settings().mode
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def ensure_engine(self):
        if self.engine is None:
            from app.trading.runner import build_engine
            self.engine, _ = build_engine()
        return self.engine

    def start(self, poll_seconds: int = 60):
        eng = self.ensure_engine()
        eng.state.running = True
        eng.state.halted = False
        eng.state.halt_reason = None
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(poll_seconds,),
                                        daemon=True)
        self._thread.start()

    def _loop(self, poll_seconds: int):
        cfg = get_settings()
        eng = self.engine
        while not self._stop.is_set() and eng.state.running:
            try:
                eng.manage_open_positions()
                for symbol in cfg.symbol_list:
                    eng.process_symbol(symbol)
            except Exception:
                pass
            self._stop.wait(poll_seconds)

    def stop(self):
        self._stop.set()
        if self.engine:
            self.engine.state.running = False


ctrl = Controller()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def status():
    eng = ctrl.engine
    if eng is None:
        return {"mode": ctrl.mode, "running": False, "halted": False}
    bal = eng.exchange.get_balance()
    s = eng.state
    return {
        "mode": ctrl.mode,
        "running": s.running,
        "halted": s.halted,
        "halt_reason": s.halt_reason,
        "balance": bal.available,
        "equity": bal.equity,
        "day_start_equity": s.day_start_equity,
        "daily_pnl": bal.equity - s.day_start_equity,
        "open_positions": len(s.open_positions),
        "consecutive_losses": s.consecutive_losses,
        "closed_trades": len(s.trades),
    }


@router.get("/positions")
def positions():
    eng = ctrl.engine
    if eng is None:
        return []
    out = []
    for sym, p in eng.state.open_positions.items():
        out.append({
            "symbol": sym, "side": p["side"].value, "qty": p["qty"],
            "entry": p["entry"], "stop": p["stop"], "tp": p.get("tp"),
            "unrealized": p.get("unrealized", 0.0),
        })
    return out


@router.get("/trades")
def trades(limit: int = 50):
    eng = ctrl.engine
    if eng is None:
        return []
    return eng.state.trades[-limit:]


@router.get("/risk")
def risk():
    eng = ctrl.engine
    if eng is None:
        return {"halted": False}
    s = eng.state
    cfg = get_settings()
    return {
        "halted": s.halted, "halt_reason": s.halt_reason,
        "consecutive_losses": s.consecutive_losses,
        "max_consecutive_losses": cfg.max_consecutive_losses,
        "risk_per_trade": cfg.risk_per_trade,
        "daily_max_loss": cfg.daily_max_loss,
        "weekly_max_loss": cfg.weekly_max_loss,
        "max_open_positions": cfg.max_open_positions,
        "max_leverage": cfg.max_leverage,
    }


@router.post("/control/start")
def start():
    ctrl.start()
    return {"running": True, "mode": ctrl.mode}


@router.post("/control/stop")
def stop():
    ctrl.stop()
    return {"running": False}


@router.post("/control/kill")
def kill():
    """EMERGENCY: stop the loop, cancel all orders, flatten, halt."""
    ctrl.stop()
    if ctrl.engine is None:
        raise HTTPException(400, "engine not running")
    ctrl.engine.kill(flatten=True)
    return {"killed": True, "halted": True}


class ModeReq(BaseModel):
    mode: str            # "paper" | "live"
    confirm_live: bool = False


@router.post("/control/mode")
def set_mode(req: ModeReq):
    if req.mode == "live" and not req.confirm_live:
        raise HTTPException(400, "going live requires confirm_live=true")
    ctrl.stop()
    ctrl.mode = req.mode
    ctrl.engine = None   # rebuilt against the right exchange on next start
    return {"mode": ctrl.mode}


class BacktestReq(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    limit: int = 1000


@router.post("/backtest")
def backtest(req: BacktestReq):
    from app.backtest.engine import Backtester
    from app.strategies.ema_rsi import EmaRsiStrategy
    from app.trading.engine import _to_df

    eng = ctrl.ensure_engine()
    candles = eng.exchange.get_candles(req.symbol, req.timeframe, limit=req.limit)
    if len(candles) < 250:
        raise HTTPException(400, "not enough candles for a backtest")
    return Backtester(EmaRsiStrategy()).run(_to_df(candles), symbol=req.symbol)
