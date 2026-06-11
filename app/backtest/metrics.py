"""Performance metrics for a list of closed trades + an equity curve.

These are the numbers you actually judge a strategy on. A high win rate means
little; profit factor, expectancy, max drawdown and Sharpe together tell the
real story. Anything that looks too good is probably overfit or look-ahead.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict


@dataclass
class BacktestMetrics:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy: float          # avg net PnL per trade ($)
    avg_r: float               # avg R-multiple
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    total_fees: float

    def as_dict(self) -> dict:
        return asdict(self)


def compute_metrics(trades: list[dict], equity_curve: list[float],
                    starting_equity: float) -> BacktestMetrics:
    n = len(trades)
    if n == 0:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    fees = sum(t.get("fees", 0.0) for t in trades)

    win_rate = len(wins) / n
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    expectancy = sum(pnls) / n
    r_vals = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0

    end_equity = equity_curve[-1] if equity_curve else starting_equity
    total_return = (end_equity / starting_equity - 1) * 100

    max_dd = _max_drawdown(equity_curve) * 100
    sharpe, sortino = _risk_ratios(equity_curve)

    return BacktestMetrics(
        trades=n, win_rate=win_rate, profit_factor=profit_factor,
        expectancy=expectancy, avg_r=avg_r, total_return_pct=total_return,
        max_drawdown_pct=max_dd, sharpe=sharpe, sortino=sortino, total_fees=fees,
    )


def _max_drawdown(curve: list[float]) -> float:
    peak = -float("inf")
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def _risk_ratios(curve: list[float]) -> tuple[float, float]:
    if len(curve) < 3:
        return 0.0, 0.0
    rets = [(curve[i] / curve[i - 1] - 1) for i in range(1, len(curve)) if curve[i - 1] > 0]
    if not rets:
        return 0.0, 0.0
    mean = sum(rets) / len(rets)
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
    downs = [r for r in rets if r < 0]
    dstd = math.sqrt(sum(r ** 2 for r in downs) / len(downs)) if downs else 0.0
    ann = math.sqrt(365 * 24)  # rough annualization for hourly bars
    sharpe = (mean / std * ann) if std > 0 else 0.0
    sortino = (mean / dstd * ann) if dstd > 0 else 0.0
    return sharpe, sortino
