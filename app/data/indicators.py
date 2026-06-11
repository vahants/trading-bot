"""Technical indicators — pure functions over a pandas DataFrame/Series.

No state, no I/O, no look-ahead: every value at index t uses only data up to t.
That property is what keeps the backtester honest. All indicators are unit-tested.

Expected DataFrame columns: open, high, low, close, volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # When avg_loss == 0 the series is all gains -> RSI 100 (not "undefined").
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    # Truly flat (no gains, no losses) -> neutral 50.
    return out.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
         ) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(period).mean()
    sd = series.rolling(period).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + std * sd, "lower": mid - std * sd})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP (intraday users should reset per session)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_pv = (typical * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return cum_pv / cum_v


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the standard indicator set used by the MVP strategy + regime."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], 50)
    out["ema_slow"] = ema(out["close"], 200)
    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out, 14)
    bb = bollinger(out["close"], 20, 2.0)
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = bb["mid"], bb["upper"], bb["lower"]
    m = macd(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = m["macd"], m["signal"], m["hist"]
    out["vol_ma"] = out["volume"].rolling(20).mean()
    return out
