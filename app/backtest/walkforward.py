"""Walk-forward validation — the honest test of whether a strategy has an edge.

A normal backtest tunes parameters and reports results on the SAME data, which
almost always looks good and almost always fails live (overfitting). Walk-forward
fixes this:

    [---- train ----][-- test --]
                 [---- train ----][-- test --]
                              [---- train ----][-- test --]

For each window we (1) pick the best parameters on the TRAIN slice, then (2)
evaluate ONLY those parameters on the immediately following TEST slice, which the
optimizer never saw. We stitch all the TEST (out-of-sample) trades together — that
out-of-sample record is the closest thing to "how it would have done live."

If in-sample looks great but out-of-sample is poor, the "edge" was curve-fitting.
"""
from __future__ import annotations

import itertools
from typing import Callable

import pandas as pd

from app.backtest.engine import Backtester
from app.strategies.base import Strategy


def _combos(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])]


def _r_list(trades: list[dict]) -> list[float]:
    return [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]


def profit_factor_R(trades: list[dict]) -> float:
    rs = _r_list(trades)
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _train_score(trades: list[dict], min_trades: int = 8) -> float:
    """Objective the optimizer maximizes on the train window. Profit factor on
    R-multiples, but disqualify parameter sets that barely traded (unreliable)."""
    if len(_r_list(trades)) < min_trades:
        return float("-inf")
    pf = profit_factor_R(trades)
    return pf if pf != float("inf") else 5.0  # cap so a lucky 0-loss train doesn't dominate


def run_walk_forward(
    df: pd.DataFrame,
    strategy_factory: Callable[..., Strategy],
    param_grid: dict,
    train_bars: int,
    test_bars: int,
    warmup: int = 200,
    starting_equity: float = 10_000.0,
    settings=None,
) -> dict:
    """Return out-of-sample trades + per-window detail.

    `strategy_factory(**params)` must build a Strategy from a param combo.
    """
    n = len(df)
    combos = _combos(param_grid)
    windows: list[dict] = []
    oos_trades: list[dict] = []

    i = 0
    while i + train_bars + test_bars <= n:
        train = df.iloc[i:i + train_bars].copy()
        # include `warmup` bars before the test window so indicators (EMA200 etc.)
        # are valid at the test start — that warmup is legitimately past data.
        test = df.iloc[i + train_bars - warmup: i + train_bars + test_bars].copy()

        # 1) optimize on TRAIN
        best_params, best_score, best_train = None, float("-inf"), None
        for params in combos:
            res = Backtester(strategy_factory(**params), starting_equity,
                             settings=settings).run(train)
            s = _train_score(res["trades"])
            if s > best_score:
                best_score, best_params, best_train = s, params, res

        if best_params is None:                 # no param set traded enough on train
            i += test_bars
            continue

        # 2) evaluate best params on TEST (out-of-sample)
        test_res = Backtester(strategy_factory(**best_params), starting_equity,
                              settings=settings).run(test)
        for t in test_res["trades"]:
            t["window"] = len(windows)
        oos_trades.extend(test_res["trades"])

        windows.append({
            "window": len(windows),
            "best_params": best_params,
            "train_pf": round(best_score, 3),
            "train_trades": best_train["num_trades"],
            "oos_trades": test_res["num_trades"],
            "oos_pf": round(profit_factor_R(test_res["trades"]), 3),
        })
        i += test_bars

    return {"windows": windows, "oos_trades": oos_trades, "combos_tested": len(combos)}
