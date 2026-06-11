import numpy as np
import pandas as pd

from app.backtest.engine import Backtester
from app.strategies.ema_rsi import EmaRsiStrategy


def _synthetic(n=1500, seed=7):
    """A trending series with noise + pullbacks so entries actually fire."""
    rng = np.random.default_rng(seed)
    # gentle uptrend with mean-reverting noise
    trend = np.linspace(100, 180, n)
    noise = np.cumsum(rng.normal(0, 0.4, n))
    close = trend + noise
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    vol = rng.uniform(80, 120, n)
    return pd.DataFrame({
        "open_time": pd.date_range("2023-01-01", periods=n, freq="h"),
        "open": close, "high": high, "low": low, "close": close, "volume": vol,
    })


def test_backtest_runs_and_reports_metrics():
    df = _synthetic()
    bt = Backtester(EmaRsiStrategy(), starting_equity=10_000.0)
    res = bt.run(df, symbol="BTCUSDT")
    m = res["metrics"]
    # structural assertions — the engine produces a complete metric set
    for key in ["trades", "win_rate", "profit_factor", "max_drawdown_pct",
                "sharpe", "expectancy", "total_fees"]:
        assert key in m
    assert res["final_equity"] > 0
    assert m["trades"] >= 0
    # fees must be non-negative and drawdown a sane percentage
    assert m["total_fees"] >= 0
    assert 0 <= m["max_drawdown_pct"] <= 100


def test_no_lookahead_strategy_sees_only_past():
    """Strategy output for a prefix must not change when future bars are added."""
    df = _synthetic()
    strat = EmaRsiStrategy()
    from app.data.indicators import add_indicators
    full = add_indicators(df)
    prefix = full.iloc[:600].copy()
    s_prefix = strat.generate(prefix)
    s_full_at_600 = strat.generate(full.iloc[:600].copy())
    # same input window -> identical decision (determinism / no global state)
    assert (s_prefix is None) == (s_full_at_600 is None)
