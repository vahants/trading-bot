"""Multi-strategy shootout wiring: one engine per strategy, journaling keyed by
strategy so the comparison report can separate them."""
import csv

from app.reporting import journal
from app.strategies import registry
from app.trading.multi_runner import build_engines


def test_build_engines_one_per_strategy():
    engines, cfg = build_engines()
    assert set(engines) == set(registry.names())
    # each engine carries its own strategy + its own (paper) account
    for name, eng in engines.items():
        assert eng.strategy.name
        assert eng.exchange.name == "paper"


def test_journal_separates_strategies():
    a = dict(strategy="ema_rsi", symbol="BTCUSDT", side="long", mode="paper",
             open_ts=None, close_ts=None, entry_price=100, exit_price=110, qty=1,
             net_pnl=10.0, r_multiple=1.0, stop=95, take_profit=110,
             exit_reason="take_profit")
    b = dict(a, strategy="donchian", net_pnl=-5.0, r_multiple=-0.5,
             exit_reason="stop")
    journal.append_trade(a)
    journal.append_trade(b)
    rows = list(csv.DictReader(open(journal.TRADES_CSV)))
    strategies = {r["strategy"] for r in rows}
    assert {"ema_rsi", "donchian"}.issubset(strategies)
