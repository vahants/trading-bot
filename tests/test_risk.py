from app.config import Settings
from app.db.models import Side
from app.exchanges.base import SymbolInfo
from app.risk.risk_manager import AccountState, RiskManager
from app.strategies.base import Signal


def _settings(**kw):
    base = dict(risk_per_trade=0.01, daily_max_loss=0.02, weekly_max_loss=0.05,
                max_open_positions=3, max_leverage=3, max_consecutive_losses=4)
    base.update(kw)
    return Settings(**base)


def _sym():
    return SymbolInfo("BTCUSDT", tick_size=0.1, qty_step=0.001, min_notional=5.0)


def _acct(**kw):
    base = dict(equity=10_000, open_positions=0, day_start_equity=10_000,
                daily_pnl=0.0, weekly_pnl=0.0, consecutive_losses=0)
    base.update(kw)
    return AccountState(**base)


def test_position_size_matches_risk():
    # entry 100, stop 98 -> risk/unit = 2. 1% of 10k = $100 -> qty = 50.
    rm = RiskManager(_settings())
    sig = Signal(side=Side.long, entry=100, stop=98, take_profit=106)
    d = rm.evaluate(sig, _acct(), _sym())
    assert d.approved
    assert abs(d.qty - 50.0) < 1e-6


def test_wider_stop_smaller_size():
    rm = RiskManager(_settings())
    tight = rm.evaluate(Signal(Side.long, 100, 99), _acct(), _sym())
    wide = rm.evaluate(Signal(Side.long, 100, 90), _acct(), _sym())
    assert wide.qty < tight.qty


def test_leverage_cap_limits_qty():
    # 1% risk with a 0.1 stop distance would imply huge size; cap at 3x notional.
    rm = RiskManager(_settings())
    d = rm.evaluate(Signal(Side.long, 100, 99.9), _acct(), _sym())
    assert d.qty * 100 <= 10_000 * 3 + 1e-6


def test_daily_loss_halts():
    rm = RiskManager(_settings())
    acct = _acct(daily_pnl=-300)  # -3% > 2% limit
    d = rm.evaluate(Signal(Side.long, 100, 98), acct, _sym())
    assert not d.approved and "daily" in d.reason


def test_consecutive_losses_halt():
    rm = RiskManager(_settings())
    acct = _acct(consecutive_losses=4)
    d = rm.evaluate(Signal(Side.long, 100, 98), acct, _sym())
    assert not d.approved and "consecutive" in d.reason


def test_max_positions_block():
    rm = RiskManager(_settings())
    d = rm.evaluate(Signal(Side.long, 100, 98), _acct(open_positions=3), _sym())
    assert not d.approved


def test_circuit_breaker():
    rm = RiskManager(_settings(circuit_breaker_atr_mult=3))
    assert rm.circuit_breaker_triggered(last_move_abs=40, atr=10) is True
    assert rm.circuit_breaker_triggered(last_move_abs=20, atr=10) is False
