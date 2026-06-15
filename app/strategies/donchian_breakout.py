"""Donchian breakout, trend-aligned — a different edge hypothesis than EMA+RSI.

Idea: real moves often start when price breaks the high/low of the last N bars
*in the direction of the higher trend*, with participation (volume). Instead of
buying a pullback (EMA+RSI), this buys strength/confirmation.

  Long:  uptrend (EMA50>EMA200) AND close breaks above the prior N-bar high
         AND volume >= its 20-bar average.  Stop = entry - k*ATR, TP = entry + m*ATR,
         trail at 2*ATR. Mirror for shorts in a downtrend.

This is NOT guaranteed to work — it's a hypothesis to be judged by walk-forward
validation, same as everything else.
"""
from __future__ import annotations

import pandas as pd

from app.data.indicators import add_indicators
from app.db.models import Side
from app.strategies.base import Signal, Strategy


class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    family = "trend"

    def __init__(self, channel: int = 20, atr_stop_mult: float = 2.0,
                 atr_tp_mult: float = 3.0):
        self.channel = channel
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult

    def generate(self, df: pd.DataFrame) -> Signal | None:
        if "ema_fast" not in df.columns:
            df = add_indicators(df)
        if len(df) < max(220, self.channel + 2) or df["atr"].iloc[-1] <= 0:
            return None

        last = df.iloc[-1]
        price, atr = last["close"], last["atr"]
        # prior channel EXCLUDING the current bar (no look-ahead)
        prior = df.iloc[-(self.channel + 1):-1]
        hh, ll = prior["high"].max(), prior["low"].min()

        vm = last.get("vol_ma")
        vol_ok = vm is None or pd.isna(vm) or last["volume"] >= vm

        uptrend = last["ema_fast"] > last["ema_slow"]
        downtrend = last["ema_fast"] < last["ema_slow"]

        if uptrend and price > hh and vol_ok:
            return Signal(
                side=Side.long, entry=price, stop=price - self.atr_stop_mult * atr,
                take_profit=price + self.atr_tp_mult * atr, trailing_atr_mult=2.0,
                family="trend", reason=f"breakout > {hh:.0f}", meta={"atr": atr},
            )
        if downtrend and price < ll and vol_ok:
            return Signal(
                side=Side.short, entry=price, stop=price + self.atr_stop_mult * atr,
                take_profit=price - self.atr_tp_mult * atr, trailing_atr_mult=2.0,
                family="trend", reason=f"breakdown < {ll:.0f}", meta={"atr": atr},
            )
        return None
