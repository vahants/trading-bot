"""RiskManager — the gatekeeper. Capital protection lives here.

Every proposed trade passes through ``evaluate()``. The manager:
  1. checks whether trading is halted (daily/weekly loss, consecutive losses,
     circuit breaker, manual kill),
  2. enforces max open positions,
  3. sizes the position from RISK, not leverage:
        qty = (equity * risk_per_trade) / risk_per_unit
     so a wider stop automatically means a smaller position,
  4. caps notional by max leverage and rounds to the symbol's qty step,
  5. rejects anything below the exchange minimum notional.

It is intentionally pessimistic. When in doubt, it says no. The strategy can
only *propose*; the RiskManager *disposes*.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.exchanges.base import SymbolInfo
from app.strategies.base import Signal


@dataclass
class AccountState:
    equity: float
    open_positions: int
    day_start_equity: float
    daily_pnl: float            # realized PnL today (negative = loss)
    weekly_pnl: float
    consecutive_losses: int
    manual_halt: bool = False
    circuit_breaker: bool = False


@dataclass
class RiskDecision:
    approved: bool
    qty: float
    reason: str
    risk_amount: float = 0.0


class RiskManager:
    def __init__(self, settings=None):
        self.cfg = settings or get_settings()

    # ---- top-level gate ----
    def evaluate(self, signal: Signal, acct: AccountState,
                 sym: SymbolInfo) -> RiskDecision:
        halt = self._halt_reason(acct)
        if halt:
            return RiskDecision(False, 0.0, f"halted: {halt}")

        if acct.open_positions >= self.cfg.max_open_positions:
            return RiskDecision(False, 0.0, "max open positions reached")

        if signal.risk_per_unit <= 0:
            return RiskDecision(False, 0.0, "invalid stop distance")

        # --- position sizing from risk ---
        risk_amount = acct.equity * self.cfg.risk_per_trade
        raw_qty = risk_amount / signal.risk_per_unit

        # --- leverage cap ---
        max_notional = acct.equity * self.cfg.max_leverage
        if raw_qty * signal.entry > max_notional:
            raw_qty = max_notional / signal.entry

        qty = self._round_step(raw_qty, sym.qty_step)
        if qty <= 0:
            return RiskDecision(False, 0.0, "sized qty rounds to zero")

        notional = qty * signal.entry
        if notional < sym.min_notional:
            return RiskDecision(False, 0.0,
                                f"notional {notional:.2f} < min {sym.min_notional}")

        return RiskDecision(True, qty,
                            f"ok; risk ${risk_amount:.2f} ({self.cfg.risk_per_trade:.1%})",
                            risk_amount=risk_amount)

    # ---- halt logic (also used directly by the engine each loop) ----
    def _halt_reason(self, acct: AccountState) -> str | None:
        if acct.manual_halt:
            return "manual kill switch"
        if acct.circuit_breaker:
            return "circuit breaker"
        if acct.consecutive_losses >= self.cfg.max_consecutive_losses:
            return f"{acct.consecutive_losses} consecutive losses"
        # daily loss limit (daily_pnl is negative on a loss)
        if acct.day_start_equity > 0:
            daily_dd = -acct.daily_pnl / acct.day_start_equity
            if daily_dd >= self.cfg.daily_max_loss:
                return f"daily loss limit {self.cfg.daily_max_loss:.1%} hit"
        # weekly loss limit (approx: vs current equity base)
        if acct.equity > 0:
            weekly_dd = -acct.weekly_pnl / acct.equity
            if weekly_dd >= self.cfg.weekly_max_loss:
                return f"weekly loss limit {self.cfg.weekly_max_loss:.1%} hit"
        return None

    def is_halted(self, acct: AccountState) -> str | None:
        return self._halt_reason(acct)

    # ---- circuit breaker check on raw price action ----
    def circuit_breaker_triggered(self, last_move_abs: float, atr: float) -> bool:
        """True if a single-bar move exceeds the configured ATR multiple."""
        if atr <= 0:
            return False
        return last_move_abs > self.cfg.circuit_breaker_atr_mult * atr

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return (int(value / step)) * step  # floor to step (never size up)
