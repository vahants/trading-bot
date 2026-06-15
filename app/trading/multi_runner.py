"""Run ALL strategies in parallel (paper), side by side, for a live shootout.

One process, one shared market-data feed (so we don't multiply API calls), and a
SEPARATE simulated account + engine per strategy. Every closed trade is journaled
with its strategy name, so `python scripts/report.py --compare` shows a per-strategy
scoreboard.

Paper only — this is for comparing strategies, not placing real orders. Run:
    python run_multi.py
Then any time:
    python scripts/report.py --compare
"""
from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.exchanges.base import TransientExchangeError

log = logging.getLogger("multi")
logging.getLogger("pybit._http_manager").setLevel(logging.CRITICAL)

_TF_MAP = {5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}


def build_engines(starting_equity: float = 10_000.0):
    cfg = get_settings()
    tf = _TF_MAP.get(cfg.base_timeframe, "1h")

    from app.exchanges.paper import PaperExchange
    from app.trading.engine import TradingEngine
    from app.strategies import registry

    # ONE shared data source — its candle/price caches dedupe across strategies.
    data_source = None
    try:
        from app.exchanges.bybit import BybitExchange
        data_source = BybitExchange(testnet=False)   # real mainnet prices, no key
    except Exception as e:
        log.warning("No Bybit data source (%s).", e)

    engines = {}
    for name in registry.names():
        paper = PaperExchange(data_source=data_source, starting_equity=starting_equity)
        engines[name] = TradingEngine(
            exchange=paper, strategy=registry.build(name), timeframe=tf,
            recorder=None, notifier=None, settings=cfg,
        )
    return engines, cfg


def run_multi(poll_seconds: int = 60):
    cfg = get_settings()
    if cfg.is_live:
        raise SystemExit("Multi-strategy mode is PAPER only. Set MODE=paper in .env.")

    engines, cfg = build_engines()
    for eng in engines.values():
        eng.state.running = True
    log.info("MULTI shootout started | strategies=%s symbols=%s tf=%s",
             list(engines), cfg.symbol_list, next(iter(engines.values())).timeframe)

    while True:
        for name, eng in engines.items():
            try:
                for ev in eng.manage_open_positions():
                    log.info("[%s] %s", name, ev)
                for symbol in cfg.symbol_list:
                    res = eng.process_symbol(symbol)
                    if res["action"] in ("entered", "closed", "rejected"):
                        log.info("[%s] %s -> %s (%s)", name, symbol,
                                 res["action"], res["reason"])
            except TransientExchangeError as e:
                log.warning("[%s] exchange busy (%s)", name, e)
            except Exception:
                log.exception("[%s] iteration error", name)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_multi()
