import numpy as np
import pandas as pd

from app.data.indicators import ema, rsi, atr, add_indicators


def _df(prices):
    n = len(prices)
    return pd.DataFrame({
        "open": prices, "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices], "close": prices,
        "volume": [100.0] * n,
    })


def test_ema_converges_to_constant():
    s = pd.Series([10.0] * 50)
    assert abs(ema(s, 10).iloc[-1] - 10.0) < 1e-9


def test_rsi_bounds_and_uptrend():
    up = pd.Series(np.linspace(1, 100, 100))
    r = rsi(up, 14)
    assert (r >= 0).all() and (r <= 100).all()
    assert r.iloc[-1] > 70  # strong uptrend => high RSI


def test_rsi_downtrend_low():
    down = pd.Series(np.linspace(100, 1, 100))
    assert rsi(down, 14).iloc[-1] < 30


def test_atr_positive():
    df = _df(list(np.linspace(100, 120, 60)))
    a = atr(df, 14)
    assert a.iloc[-1] > 0


def test_add_indicators_columns():
    df = _df(list(np.linspace(100, 200, 300)))
    out = add_indicators(df)
    for col in ["ema_fast", "ema_slow", "rsi", "atr", "bb_mid", "macd"]:
        assert col in out.columns
