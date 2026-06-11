"""Download historical OHLCV (klines) from Bybit into a CSV for backtesting.

Public market data — NO API key required (keys are only needed for trading).
Paginates backwards from now until it has `--bars` candles (Bybit returns up to
1000 per request).

Usage:
  python scripts/backfill.py --symbol BTCUSDT --timeframe 1h --bars 8000
  python scripts/backfill.py --symbol ETHUSDT --timeframe 15m --bars 20000 --out data/eth_15m.csv

Output columns: open_time,open,high,low,close,volume  (chronological, UTC).
Feed straight into:  python run_backtest.py --csv data/btc_1h.csv
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# Make the project root importable when run as `python scripts/backfill.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

# Minutes per timeframe (for stepping the pagination window).
_TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
_TF_CODE = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}


def fetch(symbol: str, timeframe: str, bars: int, category: str = "linear",
          testnet: bool = False) -> pd.DataFrame:
    from pybit.unified_trading import HTTP

    client = HTTP(testnet=testnet)  # public endpoints, no auth
    code = _TF_CODE[timeframe]
    step_ms = _TF_MIN[timeframe] * 60 * 1000
    per_call = 1000

    end_ms = int(time.time() * 1000)
    rows: dict[int, list] = {}  # keyed by open_time ms -> dedupe

    while len(rows) < bars:
        start_ms = end_ms - per_call * step_ms
        resp = client.get_kline(
            category=category, symbol=symbol, interval=code,
            start=start_ms, end=end_ms, limit=per_call,
        )
        batch = resp.get("result", {}).get("list", [])
        if not batch:
            break
        for r in batch:  # [start, open, high, low, close, volume, turnover]
            t = int(r[0])
            rows[t] = [t, float(r[1]), float(r[2]), float(r[3]),
                       float(r[4]), float(r[5])]
        oldest = min(int(r[0]) for r in batch)
        if oldest >= end_ms:        # no progress -> stop
            break
        end_ms = oldest - 1
        time.sleep(0.15)            # be gentle with the public API

    data = sorted(rows.values(), key=lambda x: x[0])[-bars:]
    df = pd.DataFrame(data, columns=["open_time", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--timeframe", default="1h", choices=list(_TF_CODE))
    p.add_argument("--bars", type=int, default=8000)
    p.add_argument("--category", default="linear")
    p.add_argument("--testnet", action="store_true")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    out = args.out or f"data/{args.symbol.lower()}_{args.timeframe}.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    print(f"Downloading {args.bars} {args.timeframe} bars of {args.symbol}...")
    df = fetch(args.symbol, args.timeframe, args.bars, args.category, args.testnet)
    df.to_csv(out, index=False)
    span = f"{df['open_time'].iloc[0]}  ->  {df['open_time'].iloc[-1]}"
    print(f"Saved {len(df)} rows to {out}\nRange: {span}")
    print(f"Next:  python run_backtest.py --csv {out}")


if __name__ == "__main__":
    main()
