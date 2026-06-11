"""Performance report from the results journal — run any time, even mid-run.

Reads data/trades.csv + data/equity.csv (written automatically by the bot) and
prints win rate, profit factor, expectancy, net PnL, max drawdown, Sharpe, etc.,
plus a per-day breakdown and the most recent trades. No database required.

Usage:
  python scripts/report.py                 # all journaled trades
  python scripts/report.py --days 10       # only the last 10 days
  python scripts/report.py --md report.md  # also save a markdown report
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.backtest.metrics import compute_metrics
from app.reporting.journal import TRADES_CSV, EQUITY_CSV


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=None, help="only the last N days")
    p.add_argument("--md", default=None, help="also write a markdown report here")
    args = p.parse_args()

    trades = _read_csv(TRADES_CSV)
    equity_rows = _read_csv(EQUITY_CSV)

    if args.days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        trades = [t for t in trades if _parse(t.get("close_ts")) and
                  _parse(t["close_ts"]) >= cutoff]
        equity_rows = [e for e in equity_rows if _parse(e.get("ts")) and
                       _parse(e["ts"]) >= cutoff]

    if not trades:
        print("No closed trades journaled yet.")
        print(f"(looked in {TRADES_CSV})")
        print("The bot writes a row here every time it closes a trade. If it has "
              "been running but shows nothing, it simply hasn't closed a trade yet.")
        return

    tlist = [{"net_pnl": _f(t["net_pnl"]),
              "r_multiple": _f(t.get("r_multiple"), None) if t.get("r_multiple") else None,
              "fees": 0.0} for t in trades]
    equity_curve = [_f(e["equity"]) for e in equity_rows] or \
        _synth_curve(tlist)
    start_eq = equity_curve[0] if equity_curve else 10_000.0

    m = compute_metrics(tlist, equity_curve, start_eq)
    net = sum(t["net_pnl"] for t in tlist)

    lines = []
    lines.append("=" * 52)
    lines.append("  TRADING PERFORMANCE REPORT")
    if args.days:
        lines.append(f"  (last {args.days} days)")
    lines.append("=" * 52)
    lines.append(f"  Closed trades   : {m.trades}")
    lines.append(f"  Net PnL         : {net:+.2f}")
    lines.append(f"  Win rate        : {m.win_rate*100:.1f}%")
    lines.append(f"  Profit factor   : {m.profit_factor:.2f}    (>1 = profitable)")
    lines.append(f"  Expectancy/trade: {m.expectancy:+.2f}")
    lines.append(f"  Avg R-multiple  : {m.avg_r:+.2f}")
    lines.append(f"  Max drawdown    : {m.max_drawdown_pct:.1f}%")
    lines.append(f"  Sharpe          : {m.sharpe:.2f}")
    if equity_rows:
        lines.append(f"  Equity now      : {equity_curve[-1]:.2f}  "
                     f"(start {start_eq:.2f})")
    lines.append("-" * 52)

    # per-day PnL
    by_day = defaultdict(lambda: [0.0, 0])
    for t in trades:
        d = (t.get("close_ts") or "")[:10]
        by_day[d][0] += _f(t["net_pnl"])
        by_day[d][1] += 1
    lines.append("  Daily PnL:")
    for d in sorted(by_day):
        pnl, n = by_day[d]
        lines.append(f"    {d}  {pnl:+10.2f}  ({n} trades)")
    lines.append("-" * 52)

    # last trades
    lines.append("  Last 10 trades:")
    for t in trades[-10:]:
        lines.append(f"    {(t.get('close_ts') or '')[:16]}  {t.get('symbol','?'):9} "
                     f"{t.get('side','?'):5} {_f(t['net_pnl']):+9.2f}  "
                     f"{t.get('exit_reason','')}")
    lines.append("=" * 52)

    report = "\n".join(lines)
    print(report)

    if args.md:
        with open(args.md, "w") as f:
            f.write("```\n" + report + "\n```\n")
        print(f"\nSaved markdown report to {args.md}")


def _parse(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _synth_curve(tlist):
    """If no equity log exists, rebuild a curve from trade PnLs (approx)."""
    eq, curve = 10_000.0, [10_000.0]
    for t in tlist:
        eq += t["net_pnl"]
        curve.append(eq)
    return curve


if __name__ == "__main__":
    main()
