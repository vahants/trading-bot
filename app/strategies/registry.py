"""Strategy registry — one place to look up strategies by name and their
parameter grids for validation. Add a strategy here and it's instantly available
to `validate.py`, the runner (via STRATEGY in .env), and the API.

Param grids are kept SMALL on purpose: more knobs = easier to overfit. They are
the search space walk-forward optimizes over on each train window.
"""
from __future__ import annotations

from app.strategies.base import Strategy
from app.strategies.ema_rsi import EmaRsiStrategy
from app.strategies.donchian_breakout import DonchianBreakoutStrategy
from app.strategies.bb_meanrev import BollingerMeanReversionStrategy

# name -> (class, param_grid)
REGISTRY: dict[str, tuple[type[Strategy], dict]] = {
    "ema_rsi": (EmaRsiStrategy, {
        "atr_stop_mult": [1.5, 2.0, 2.5],
        "atr_tp_mult": [2.0, 2.5, 3.0],
    }),
    "donchian": (DonchianBreakoutStrategy, {
        "channel": [20, 40],
        "atr_stop_mult": [1.5, 2.0],
        "atr_tp_mult": [2.5, 3.5],
    }),
    "bb_meanrev": (BollingerMeanReversionStrategy, {
        "rsi_low": [25, 30],
        "atr_stop_mult": [1.5, 2.5],
    }),
}


def names() -> list[str]:
    return list(REGISTRY)


def build(name: str, **params) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy '{name}'. Known: {names()}")
    return REGISTRY[name][0](**params)


def grid(name: str) -> dict:
    return REGISTRY[name][1]
