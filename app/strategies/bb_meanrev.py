"""Bollinger mean-reversion, range-only — the opposite hypothesis to trend.

Idea: when the market is RANGING (not trending), price that stretches to an
extreme tends to snap back to the mean. Enter against the stretch, target the
middle band, hard stop beyond the extreme.

  Long:  close <= lower Bollinger(20,2) AND RSI < rsi_low (oversold).
         TP = middle band (the mean). Stop = entry - k*ATR.
  Short: mirror at the upper band with RSI > rsi_high.

The regime filter only lets this trade in "range" conditions — running mean-
reversion in a strong trend is how you get run over, so that gate matters here.
Judged by walk-forward validation like everything else.
"""
from __future__ import annotations

import pandas as pd

from app.data.indicators import add_indicators
from app.db.models import Side
from app.strategies.base import Signal, Strategy


class BollingerMeanReversionStrategy(Strategy):
    name = "bb_meanrev"
    family = "mean_reversion"

    def __init__(self, rsi_low: float = 30.0, atr_stop_mult: float = 2.0):
        self.rsi_low = rsi_low
        self.rsi_high = 100.0 - rsi_low      # symmetric
        self.atr_stop_mult = atr_stop_mult

    def generate(self, df: pd.DataFrame) -> Signal | None:
        if "bb_lower" not in df.columns:
            df = add_indicators(df)
        if len(df) < 220 or df["atr"].iloc[-1] <= 0:
            return None

        last = df.iloc[-1]
        price, atr, mid = last["close"], last["atr"], last["bb_mid"]
        if pd.isna(mid):
            return None

        # oversold at the lower band -> expect snap back up to the mean
        if price <= last["bb_lower"] and last["rsi"] < self.rsi_low and mid > price:
            return Signal(
                side=Side.long, entry=price, stop=price - self.atr_stop_mult * atr,
                take_profit=mid, trailing_atr_mult=None, family="mean_reversion",
                reason=f"below BB, RSI {last['rsi']:.0f}", meta={"atr": atr},
            )
        # overbought at the upper band -> expect snap back down to the mean
        if price >= last["bb_upper"] and last["rsi"] > self.rsi_high and mid < price:
            return Signal(
                side=Side.short, entry=price, stop=price + self.atr_stop_mult * atr,
                take_profit=mid, trailing_atr_mult=None, family="mean_reversion",
                reason=f"above BB, RSI {last['rsi']:.0f}", meta={"atr": atr},
            )
        return None
