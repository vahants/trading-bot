"""Validate whether a strategy has a REAL edge — walk-forward, out-of-sample.

This is the gate before paper/live. It optimizes parameters on past data and
tests them on later unseen data, repeatedly, then judges the out-of-sample (OOS)
record net of fees. It prints a blunt verdict: edge / marginal / overfit / no edge.

Usage:
  python scripts/backfill.py --symbol BTCUSDT --timeframe 1h --bars 12000
  python scripts/validate.py --csv data/btcusdt_1h.csv --strategy ema_rsi
  python scripts/validate.py --csv data/btcusdt_1h.csv --strategy all   # compare all

Interpreting it: profit factor > ~1.3 and positive expectancy that HOLDS across
most windows = promising. Great in-sample but poor OOS = overfit (don't trade it).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.backtest.walkforward import run_walk_forward, profit_factor_R, _r_list
from app.strategies import registry


def _agg(trades):
    rs = _r_list(trades)
    n = len(rs)
    if n == 0:
        return dict(trades=0, win_rate=0.0, pf=0.0, expectancy_R=0.0)
    wins = [r for r in rs if r > 0]
    return dict(trades=n, win_rate=len(wins) / n, pf=profit_factor_R(trades),
                expectancy_R=sum(rs) / n)


def _verdict(oos, windows):
    if oos["trades"] < 30:
        return ("INSUFFICIENT DATA",
                f"Only {oos['trades']} out-of-sample trades — need ~30+ to judge. "
                f"Use more --bars or a lower timeframe.")
    pct_win_windows = (sum(1 for w in windows if w["oos_pf"] >= 1.0) / len(windows)
                       if windows else 0)
    avg_train_pf = sum(w["train_pf"] for w in windows) / len(windows) if windows else 0
    pf, exp = oos["pf"], oos["expectancy_R"]
    if pf >= 1.3 and exp > 0 and pct_win_windows >= 0.6:
        return ("EDGE HOLDS OUT-OF-SAMPLE",
                "Promising. Proceed to weeks of PAPER trading before any live capital.")
    if pf >= 1.1 and exp > 0:
        return ("MARGINAL",
                "Weak positive OOS edge — fragile. More data / refinement needed.")
    if avg_train_pf >= 1.3 and pf < 1.0:
        return ("OVERFIT",
                "Good in-sample but FAILS out-of-sample. Do NOT trade this as-is.")
    return ("NO EDGE",
            "Out-of-sample expectancy isn't positive after fees. Revise or replace.")


def run_one(df, name, train, test):
    wf = run_walk_forward(
        df, strategy_factory=lambda **kw: registry.build(name, **kw),
        param_grid=registry.grid(name), train_bars=train, test_bars=test,
    )
    oos = _agg(wf["oos_trades"])
    label, advice = _verdict(oos, wf["windows"])
    return wf, oos, label, advice


def report_one(name, wf, oos, label, advice):
    L = []
    L.append("=" * 60)
    L.append(f"  WALK-FORWARD VALIDATION — strategy: {name}")
    L.append("  (out-of-sample, net of fees)")
    L.append("=" * 60)
    L.append(f"  Windows tested      : {len(wf['windows'])}")
    L.append(f"  OOS trades          : {oos['trades']}")
    L.append(f"  OOS win rate        : {oos['win_rate']*100:.1f}%")
    L.append(f"  OOS profit factor   : {oos['pf']:.2f}   (>1.3 good, <1.0 losing)")
    L.append(f"  OOS expectancy      : {oos['expectancy_R']:+.3f} R per trade")
    L.append("-" * 60)
    L.append("  Per-window (train PF -> out-of-sample PF):")
    for w in wf["windows"]:
        L.append(f"    #{w['window']:<2} {w['best_params']}  "
                 f"train {w['train_pf']:.2f} -> OOS {w['oos_pf']:.2f} "
                 f"({w['oos_trades']} trades)")
    L.append("-" * 60)
    by_reg = defaultdict(list)
    for t in wf["oos_trades"]:
        if t.get("r_multiple") is not None:
            by_reg[t.get("regime") or "?"].append(t["r_multiple"])
    L.append("  OOS by regime (avg R, count):")
    for reg, rs in sorted(by_reg.items()):
        L.append(f"    {reg:12} {sum(rs)/len(rs):+.3f} R   ({len(rs)} trades)")
    by_exit = defaultdict(list)
    for t in wf["oos_trades"]:
        if t.get("r_multiple") is not None:
            by_exit[t.get("exit_reason") or "?"].append(t["r_multiple"])
    L.append("  OOS by exit reason:")
    for ex, rs in sorted(by_exit.items()):
        L.append(f"    {ex:12} {sum(rs)/len(rs):+.3f} R   ({len(rs)} trades)")
    L.append("=" * 60)
    L.append(f"  VERDICT [{name}]: {label}")
    L.append(f"  {advice}")
    L.append("=" * 60)
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--strategy", default="ema_rsi",
                   help=f"{', '.join(registry.names())}, or 'all'")
    p.add_argument("--train", type=int, default=2500)
    p.add_argument("--test", type=int, default=800)
    p.add_argument("--md", default=None)
    args = p.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["open_time"])
    need = args.train + args.test + 200
    if len(df) < need:
        print(f"Only {len(df)} bars; need >= {need}. Download more (--bars) "
              f"or lower --train/--test.")
        return

    targets = registry.names() if args.strategy == "all" else [args.strategy]
    if args.strategy != "all" and args.strategy not in registry.names():
        print(f"Unknown strategy '{args.strategy}'. Options: {registry.names()} or 'all'")
        return

    blocks, summary = [], []
    for name in targets:
        print(f"Running walk-forward: {name} ...")
        wf, oos, label, advice = run_one(df, name, args.train, args.test)
        blocks.append(report_one(name, wf, oos, label, advice))
        summary.append((name, oos, label))

    out = "\n\n".join(blocks)
    if len(targets) > 1:
        out += "\n\n" + "=" * 60 + "\n  COMPARISON\n" + "=" * 60 + "\n"
        out += f"  {'strategy':14}{'trades':>7}{'win%':>7}{'PF':>7}{'exp_R':>8}   verdict\n"
        for name, oos, label in summary:
            out += (f"  {name:14}{oos['trades']:>7}{oos['win_rate']*100:>6.0f}%"
                    f"{oos['pf']:>7.2f}{oos['expectancy_R']:>+8.3f}   {label}\n")
        out += ("  -> Keep only a strategy with a clear out-of-sample edge, then "
                "PAPER-trade it. Most will not pass; that's expected.\n")

    print("\n" + out)
    if args.md:
        with open(args.md, "w") as f:
            f.write("```\n" + out + "\n```\n")
        print(f"\nSaved {args.md}")
    print("\nReminder: passing here is NECESSARY, not SUFFICIENT. Paper-trade next; "
          "live fills differ. No result guarantees profit.")


if __name__ == "__main__":
    main()
