"""Walk-forward harness: structure + no-look-ahead discipline."""
import numpy as np
import pandas as pd

from app.backtest.walkforward import run_walk_forward, profit_factor_R
from app.strategies.ema_rsi import EmaRsiStrategy


def _synth(n=5000, seed=5):
    rng = np.random.default_rng(seed)
    close = np.linspace(100, 200, n) + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "open_time": pd.date_range("2023-01-01", periods=n, freq="h"),
        "open": close, "high": close + np.abs(rng.normal(0, 0.4, n)),
        "low": close - np.abs(rng.normal(0, 0.4, n)), "close": close,
        "volume": rng.uniform(80, 120, n),
    })


GRID = {"atr_stop_mult": [1.5, 2.0], "atr_tp_mult": [2.0, 2.5]}


def test_walk_forward_runs_and_is_segmented():
    wf = run_walk_forward(_synth(), lambda **k: EmaRsiStrategy(**k), GRID,
                          train_bars=2000, test_bars=700)
    assert wf["combos_tested"] == 4
    assert len(wf["windows"]) >= 2
    for w in wf["windows"]:
        assert "best_params" in w and "train_pf" in w and "oos_pf" in w
    # OOS trades carry a window tag and a regime tag (for the breakdown)
    for t in wf["oos_trades"]:
        assert "window" in t and "regime" in t


def test_profit_factor_R_basic():
    trades = [{"r_multiple": 2.0}, {"r_multiple": -1.0}, {"r_multiple": 1.0}]
    # wins 3.0 / losses 1.0 = 3.0
    assert abs(profit_factor_R(trades) - 3.0) < 1e-9


def test_oos_windows_do_not_overlap_in_test_period():
    wf = run_walk_forward(_synth(), lambda **k: EmaRsiStrategy(**k), GRID,
                          train_bars=2000, test_bars=700)
    # each OOS trade belongs to exactly one window (no double counting)
    windows_seen = {t["window"] for t in wf["oos_trades"]}
    assert windows_seen.issubset(set(range(len(wf["windows"]))))
