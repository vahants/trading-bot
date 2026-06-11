"""MVP strategy: EMA trend filter + RSI pullback entry (trend-following).

Idea (deliberately simple — simple strategies overfit less):
  * Trend filter: EMA(50) above EMA(200) => only longs; below => only shorts.
  * Entry (long): in an uptrend, wait for a pullback (RSI dipped below ~45) then
    enter when momentum resumes (RSI crosses back above 50). Mirror for shorts.
  * Stop: 2 * ATR from entry (volatility-adaptive — wider stop in wild markets,
    which the RiskManager turns into a smaller position).
  * Take-profit: 2.5 * ATR (~1.25R). Trailing stop at 2*ATR once price moves +1R.
  * Invalidation: EMA(50) crossing back through EMA(200) kills the thesis.

This is NOT a money printer. It is a clean, testable baseline to validate the
whole pipeline. Whether it has a real edge after fees is for the backtester to
judge — and most simple strategies do not. That's the point of testing.
"""
from __future__ import annotations

import pandas as pd

from app.data.indicators import add_indicators
from app.db.models import Side
from app.strategies.base import Signal, Strategy


class EmaRsiStrategy(Strategy):
    name = "ema_rsi_trend"
    family = "trend"

    def __init__(self, atr_stop_mult: float = 2.0, atr_tp_mult: float = 2.5,
                 rsi_pullback: float = 45.0, rsi_trigger: float = 50.0):
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult
        self.rsi_pullback = rsi_pullback
        self.rsi_trigger = rsi_trigger

    def generate(self, df: pd.DataFrame) -> Signal | None:
        if "ema_fast" not in df.columns:
            df = add_indicators(df)
        if len(df) < 200 or df["atr"].iloc[-1] <= 0:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        price, atr = last["close"], last["atr"]
        uptrend = last["ema_fast"] > last["ema_slow"]
        downtrend = last["ema_fast"] < last["ema_slow"]

        # --- long setup ---
        if uptrend and price > last["ema_slow"]:
            pulled_back = prev["rsi"] < self.rsi_pullback
            resuming = prev["rsi"] <= self.rsi_trigger < last["rsi"]
            if pulled_back and resuming:
                stop = price - self.atr_stop_mult * atr
                tp = price + self.atr_tp_mult * atr
                return Signal(
                    side=Side.long, entry=price, stop=stop, take_profit=tp,
                    trailing_atr_mult=2.0, family=self.family,
                    reason=f"uptrend pullback; RSI {prev['rsi']:.0f}->{last['rsi']:.0f}",
                    meta={"atr": atr},
                )

        # --- short setup (mirror) ---
        if downtrend and price < last["ema_slow"]:
            pulled_back = prev["rsi"] > (100 - self.rsi_pullback)
            resuming = prev["rsi"] >= (100 - self.rsi_trigger) > last["rsi"]
            if pulled_back and resuming:
                stop = price + self.atr_stop_mult * atr
                tp = price - self.atr_tp_mult * atr
                return Signal(
                    side=Side.short, entry=price, stop=stop, take_profit=tp,
                    trailing_atr_mult=2.0, family=self.family,
                    reason=f"downtrend pullback; RSI {prev['rsi']:.0f}->{last['rsi']:.0f}",
                    meta={"atr": atr},
                )

        return None
