"""Zero-setup results journal — appends every closed trade and equity snapshot
to CSV files under ``data/`` so results SURVIVE restarts with no database.

This is what lets you run for days, restart whenever, and still get a full
performance report from ``scripts/report.py``. Postgres (via Recorder) is
optional and additive; this file journal always works.
"""
from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone

# project_root/data/...   (journal.py is at app/reporting/journal.py)
# Override with TRADING_BOT_DATA_DIR (tests point this at a temp dir).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.environ.get("TRADING_BOT_DATA_DIR") or os.path.join(_ROOT, "data")

TRADES_CSV = os.path.join(_DATA_DIR, "trades.csv")
EQUITY_CSV = os.path.join(_DATA_DIR, "equity.csv")

_LOCK = threading.Lock()  # the API runs the loop in a thread; keep writes atomic

_TRADE_FIELDS = [
    "close_ts", "open_ts", "mode", "symbol", "strategy", "side", "qty",
    "entry_price", "exit_price", "net_pnl", "r_multiple", "stop", "take_profit",
    "exit_reason",
]
_EQUITY_FIELDS = ["ts", "mode", "equity", "balance", "open_positions", "daily_pnl"]


def _append(path: str, fields: list[str], row: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with _LOCK, open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: _fmt(row.get(k)) for k in fields})


def _fmt(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def append_trade(trade: dict) -> None:
    """Best-effort — never raise into the trading loop."""
    try:
        _append(TRADES_CSV, _TRADE_FIELDS, trade)
    except Exception:
        pass


def append_equity(mode: str, equity: float, balance: float,
                  open_positions: int, daily_pnl: float) -> None:
    try:
        _append(EQUITY_CSV, _EQUITY_FIELDS, {
            "ts": datetime.now(timezone.utc).isoformat(), "mode": mode,
            "equity": equity, "balance": balance,
            "open_positions": open_positions, "daily_pnl": daily_pnl,
        })
    except Exception:
        pass
