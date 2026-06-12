"""Runner — builds the engine for the current MODE and runs the trading loop.

MODE=paper  →  PaperExchange (simulated fills) fed by REAL Bybit market data.
MODE=live   →  BybitExchange (real orders on testnet or mainnet per BYBIT_TESTNET).

Either way the SAME TradingEngine pipeline runs. Each tick:
    1. manage open positions (trail / stop / take-profit)
    2. look for new entries on each symbol
    3. snapshot equity

Run via the project entrypoint:  python run.py
"""
from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.exchanges.base import TransientExchangeError

log = logging.getLogger("runner")

_TF_MAP = {5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}


def build_engine(starting_equity: float = 10_000.0):
    """Construct a ready-to-run TradingEngine wired for the configured MODE."""
    cfg = get_settings()
    tf = _TF_MAP.get(cfg.base_timeframe, "1h")

    from app.trading.engine import TradingEngine
    from app.strategies.ema_rsi import EmaRsiStrategy
    from app.db.recorder import Recorder
    from app.alerts.telegram import TelegramNotifier

    recorder = Recorder(mode="live" if cfg.is_live else "paper")
    notifier = TelegramNotifier(cfg)

    if cfg.is_live:
        from app.exchanges.bybit import BybitExchange
        exchange = BybitExchange()
        # set leverage on each symbol (capped by the exchange & our risk rules)
        for sym in cfg.symbol_list:
            try:
                exchange.set_leverage(sym, cfg.max_leverage)
            except Exception as e:
                log.warning("set_leverage(%s) failed: %s", sym, e)
    else:
        from app.exchanges.paper import PaperExchange
        data_source = None
        try:
            from app.exchanges.bybit import BybitExchange
            # Paper uses REAL mainnet market data (public, no key) for realistic
            # prices — testnet data is thin/erratic and pollutes paper results.
            data_source = BybitExchange(testnet=False)
        except Exception as e:
            log.warning("No Bybit data source (%s) — inject candles manually.", e)
        exchange = PaperExchange(data_source=data_source, starting_equity=starting_equity)

    engine = TradingEngine(
        exchange=exchange, strategy=EmaRsiStrategy(), timeframe=tf,
        recorder=recorder, notifier=notifier, settings=cfg,
    )
    return engine, cfg


def run_loop(poll_seconds: int = 60):
    engine, cfg = build_engine()
    engine.state.running = True
    mode = "LIVE" if cfg.is_live else "PAPER"
    log.info("%s loop started | symbols=%s tf=%s testnet=%s",
             mode, cfg.symbol_list, engine.timeframe, cfg.bybit_testnet)

    while engine.state.running:
        try:
            # 1) manage what we already hold
            for ev in engine.manage_open_positions():
                log.info("manage: %s", ev)
            # 2) hunt for new entries
            for symbol in cfg.symbol_list:
                res = engine.process_symbol(symbol)
                if res["action"] != "none":
                    log.info("%s -> %s (%s)", symbol, res["action"], res["reason"])
            # the engine may stop itself on a fatal/permanent exchange block
            if not engine.state.running:
                log.error("Bot stopped: %s", engine.state.halt_reason)
                break
            # 3) record equity (DB if available, always to the CSV journal)
            bal = engine.exchange.get_balance()
            daily_pnl = bal.equity - engine.state.day_start_equity
            engine.recorder.save_equity(
                equity=bal.equity, balance=bal.available,
                open_positions=len(engine.state.open_positions),
                daily_pnl=daily_pnl, drawdown=0.0,
            )
            from app.reporting import journal
            journal.append_equity(
                mode=engine.mode, equity=bal.equity, balance=bal.available,
                open_positions=len(engine.state.open_positions), daily_pnl=daily_pnl,
            )
        except TransientExchangeError as e:
            # Rate limits / SDK quirks — expected, self-healing. One quiet line.
            log.warning("exchange busy (%s) — retrying next cycle", e)
        except Exception as e:
            # Network hiccups (timeouts, dropped connections) are also expected.
            # Only truly unexpected errors get a full traceback.
            name = type(e).__name__
            if any(k in name for k in ("Timeout", "Connection", "ReadTimeout")):
                log.warning("network hiccup (%s) — retrying next cycle", name)
            else:
                log.exception("loop iteration error")
        time.sleep(poll_seconds)
