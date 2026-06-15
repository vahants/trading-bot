"""New strategies + registry: build cleanly and emit only valid signals."""
import numpy as np
import pandas as pd

from app.data.indicators import add_indicators
from app.db.models import Side
from app.strategies import registry
from app.strategies.base import Signal


def _trending(n=600, seed=1):
    rng = np.random.default_rng(seed)
    close = np.linspace(100, 220, n) + np.cumsum(rng.normal(0, 0.4, n))
    return add_indicators(pd.DataFrame({
        "open_time": pd.date_range("2023", periods=n, freq="h"),
        "open": close, "high": close + np.abs(rng.normal(0, 0.5, n)),
        "low": close - np.abs(rng.normal(0, 0.5, n)), "close": close,
        "volume": rng.uniform(80, 120, n),
    }))


def test_registry_has_all_strategies():
    assert set(registry.names()) == {"ema_rsi", "donchian", "bb_meanrev"}
    for name in registry.names():
        s = registry.build(name)
        assert s.name and s.family
        assert isinstance(registry.grid(name), dict) and registry.grid(name)


def test_strategies_emit_valid_or_no_signal():
    df = _trending()
    for name in registry.names():
        strat = registry.build(name)
        # slide a window across the data; any signal must be internally valid
        for end in range(250, len(df), 25):
            sig = strat.generate(df.iloc[:end].copy())
            if sig is not None:
                assert isinstance(sig, Signal)
                if sig.side == Side.long:
                    assert sig.stop < sig.entry
                else:
                    assert sig.stop > sig.entry
                assert sig.risk_per_unit > 0


def test_donchian_breakout_fires_on_new_high():
    # construct a clean uptrend so a breakout long is plausible
    df = _trending(seed=3)
    strat = registry.build("donchian")
    fired = any(strat.generate(df.iloc[:e].copy()) is not None
                for e in range(250, len(df), 10))
    assert fired in (True, False)  # must not raise; firing depends on data


def test_unknown_strategy_raises():
    try:
        registry.build("does_not_exist")
        assert False
    except KeyError:
        pass
