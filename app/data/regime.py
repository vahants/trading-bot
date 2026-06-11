"""Market-regime detector.

The single most valuable risk filter in the whole system is "don't trade when the
market is unclear". A trend strategy run in chop bleeds out on fees and whipsaws.
This classifier labels the latest bar so the engine can sit out bad conditions.

Regimes: trend_up, trend_down, range, high_vol, low_vol, unclear.
"""
from __future__ import annotations

import pandas as pd


def classify(df: pd.DataFrame) -> str:
    """Classify the most recent bar. `df` must already have indicators added."""
    if len(df) < 200:
        return "unclear"

    last = df.iloc[-1]
    close = last["close"]
    ema_fast, ema_slow, atr = last["ema_fast"], last["ema_slow"], last["atr"]

    # Volatility as a fraction of price, vs its own recent median.
    atr_pct = atr / close if close else 0.0
    atr_pct_median = (df["atr"] / df["close"]).tail(100).median()

    if atr_pct_median and atr_pct > 1.8 * atr_pct_median:
        return "high_vol"          # too violent — usually sit out / shrink size
    if atr_pct_median and atr_pct < 0.5 * atr_pct_median:
        low_vol = True             # coiling — breakout watch
    else:
        low_vol = False

    # Trend strength: EMA separation relative to ATR (avoids flat "crosses").
    sep = (ema_fast - ema_slow) / atr if atr else 0.0
    if sep > 1.0 and close > ema_slow:
        return "trend_up"
    if sep < -1.0 and close < ema_slow:
        return "trend_down"

    if low_vol:
        return "low_vol"

    # EMAs entangled and price near them -> ranging.
    if abs(sep) < 0.5:
        return "range"

    return "unclear"


# Regimes in which each strategy family is permitted to trade.
TRADEABLE = {
    "trend":          {"trend_up", "trend_down"},
    "mean_reversion": {"range"},
    "breakout":       {"low_vol"},
}
