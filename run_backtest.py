"""CLI: run a backtest of the EMA+RSI strategy.

Usage:
  # against live Bybit data (needs pybit; keys optional for public klines):
  python run_backtest.py --symbol BTCUSDT --timeframe 1h --limit 1500

  # against a CSV with columns open_time,open,high,low,close,volume:
  python run_backtest.py --csv data/btc_1h.csv

Remember: a good-looking backtest is necessary but NOT sufficient. Validate
out-of-sample and across bull/bear/sideways/crash before trusting it.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from app.backtest.engine import Backtester
from app.strategies.ema_rsi import EmaRsiStrategy


def load_from_exchange(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    from app.exchanges.bybit import BybitExchange
    from app.trading.engine import _to_df
    return _to_df(BybitExchange().get_candles(symbol, timeframe, limit=limit))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--limit", type=int, default=1500)
    p.add_argument("--csv", default=None)
    p.add_argument("--equity", type=float, default=10_000.0)
    args = p.parse_args()

    if args.csv:
        df = pd.read_csv(args.csv, parse_dates=["open_time"])
    else:
        df = load_from_exchange(args.symbol, args.timeframe, args.limit)

    bt = Backtester(EmaRsiStrategy(), starting_equity=args.equity)
    result = bt.run(df, symbol=args.symbol)
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main()
