"""TradingEngine — the shared per-tick pipeline used by BOTH paper and live.

Because paper and live differ ONLY in which AbstractExchange is injected, this one
class is the single source of truth for how a decision is made and executed. The
ordering enforces the authority model from ARCHITECTURE.md §1:

    candles → indicators → regime filter → news filter → strategy signal
            → AI score (advisory) → risk sizing + veto → order validation → execute

Two responsibilities each tick:
  1. ``manage_open_positions()`` — trail stops and exit on stop/TP/trailing.
  2. ``process_symbol()``        — look for a new entry (only if flat on that symbol).

For real exchanges the protective stop also rests ON the exchange (so a crash
can't strip protection). The paper simulator has no order book, so the engine
checks price each tick and closes the position itself.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.ai.analyst import AIAnalyst
from app.config import get_settings
from app.data.indicators import add_indicators
from app.data.regime import classify, TRADEABLE
from app.db.models import Side
from app.exchanges.base import (
    AbstractExchange, OrderRequest, OrderSide, OrderType, PermanentOrderError,
)
from app.news.calendar import NewsFilter
from app.risk.risk_manager import AccountState, RiskManager
from app.strategies.base import Strategy


@dataclass
class EngineState:
    running: bool = False
    halted: bool = False
    halt_reason: str | None = None
    open_positions: dict = field(default_factory=dict)  # symbol -> position dict
    consecutive_losses: int = 0
    day_start_equity: float = 0.0
    week_start_equity: float = 0.0
    current_day: str = ""
    trades: list = field(default_factory=list)          # in-memory trade history
    # symbol -> open_time of the last candle we already evaluated for entry.
    # Prevents re-deciding the same (forming) candle every poll = no overtrading.
    last_candle_ts: dict = field(default_factory=dict)
    # symbol -> datetime until which entries are paused after a failed order.
    entry_cooldown_until: dict = field(default_factory=dict)


class TradingEngine:
    def __init__(self, exchange: AbstractExchange, strategy: Strategy,
                 timeframe: str = "1h", news: NewsFilter | None = None,
                 recorder=None, notifier=None, settings=None):
        self.cfg = settings or get_settings()
        self.exchange = exchange
        self.strategy = strategy
        self.timeframe = timeframe
        self.risk = RiskManager(self.cfg)
        self.ai = AIAnalyst(min_score=self.cfg.min_ai_score)
        self.news = news or NewsFilter()
        self.recorder = recorder      # optional DB persistence (best-effort)
        self.notifier = notifier      # optional Telegram/Discord alerts
        self.state = EngineState()
        bal = exchange.get_balance()
        self.state.day_start_equity = bal.equity
        self.state.week_start_equity = bal.equity
        self.state.current_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def mode(self) -> str:
        return "live" if self.cfg.is_live else "paper"

    # ===================================================================
    # POSITION MANAGEMENT — runs every tick before looking for new entries
    # ===================================================================
    def manage_open_positions(self) -> list[dict]:
        events = []
        for symbol in list(self.state.open_positions.keys()):
            pos = self.state.open_positions[symbol]
            price = self.exchange.get_last_price(symbol)
            pos["unrealized"] = self._pnl(pos, price)

            # trailing stop: ratchet only in our favour
            if pos.get("trail_mult") and pos.get("atr"):
                dist = pos["trail_mult"] * pos["atr"]
                if pos["side"] == Side.long:
                    pos["stop"] = max(pos["stop"], price - dist)
                else:
                    pos["stop"] = min(pos["stop"], price + dist)

            reason = self._exit_reason(pos, price)
            if reason:
                events.append(self._close_position(symbol, price, reason))
        return events

    def _exit_reason(self, pos: dict, price: float) -> str | None:
        if pos["side"] == Side.long:
            if price <= pos["stop"]:
                return "stop"
            if pos.get("tp") and price >= pos["tp"]:
                return "take_profit"
        else:
            if price >= pos["stop"]:
                return "stop"
            if pos.get("tp") and price <= pos["tp"]:
                return "take_profit"
        return None

    def _close_position(self, symbol: str, price: float, reason: str) -> dict:
        pos = self.state.open_positions.pop(symbol)
        close_side = OrderSide.sell if pos["side"] == Side.long else OrderSide.buy
        # Market reduce-only close. On paper this realizes PnL into equity.
        self.exchange.place_order(OrderRequest(
            symbol=symbol, side=close_side, type=OrderType.market,
            qty=pos["qty"], reduce_only=True,
            client_order_id="bot-" + uuid.uuid4().hex[:18],
        ))
        if self.exchange.supports_resting_stops:
            self.exchange.cancel_all(symbol)  # remove the resting stop

        gross = self._pnl(pos, price)
        r_mult = (gross / (pos["risk_per_unit"] * pos["qty"])
                  if pos.get("risk_per_unit") else None)
        is_loss = gross < 0
        self.state.consecutive_losses = self.state.consecutive_losses + 1 if is_loss else 0

        trade = {
            "symbol": symbol, "strategy": self.strategy.name,
            "side": pos["side"].value, "mode": self.mode,
            "open_ts": pos["opened_ts"], "close_ts": datetime.now(timezone.utc),
            "entry_price": pos["entry"], "exit_price": price, "qty": pos["qty"],
            "net_pnl": gross, "r_multiple": r_mult, "stop": pos["stop"],
            "take_profit": pos.get("tp"), "exit_reason": reason,
        }
        self.state.trades.append(trade)
        self._record_trade(trade)
        self._alert(f"CLOSE {symbol} {pos['side'].value} @ {price:.2f} "
                    f"({reason}) PnL {gross:+.2f} "
                    f"[{'LOSS' if is_loss else 'win'}]")
        return {"symbol": symbol, "action": "closed", "reason": reason,
                "pnl": gross, "r": r_mult}

    @staticmethod
    def _pnl(pos: dict, price: float) -> float:
        direction = 1 if pos["side"] == Side.long else -1
        return (price - pos["entry"]) * direction * pos["qty"]

    # ===================================================================
    # ENTRY PIPELINE — one decision cycle for one symbol
    # ===================================================================
    def process_symbol(self, symbol: str) -> dict:
        result = {"symbol": symbol, "action": "none", "reason": ""}
        self._maybe_rollover_day()

        acct = self._account_state()
        halt = self.risk.is_halted(acct)
        if halt:
            self.state.halted = True
            self.state.halt_reason = halt
            result.update(action="blocked", reason=f"halt: {halt}")
            return result
        self.state.halted = False

        # 1) data + indicators
        candles = self.exchange.get_candles(symbol, self.timeframe, limit=400)
        if len(candles) < 200:
            result.update(reason="not enough candles")
            return result
        df = add_indicators(_to_df(candles))

        # 2) circuit breaker on the latest bar
        last = df.iloc[-1]
        move = abs(last["close"] - last["open"])
        if self.risk.circuit_breaker_triggered(move, last["atr"]):
            result.update(action="blocked", reason="circuit breaker: abnormal bar")
            return result

        # 3) regime filter
        regime = classify(df)
        if regime not in TRADEABLE.get(self.strategy.family, set()):
            result.update(reason=f"regime '{regime}' not tradeable")
            return result

        # 4) news filter
        blocked, why = self.news.is_blocked()
        if blocked:
            result.update(action="blocked", reason=why)
            return result

        # --- make an entry decision ONLY ONCE per new candle ---
        # The loop polls every minute but candles are e.g. 15m, so without this
        # gate the same signal would re-fire ~15x and spam duplicate orders.
        candle_ts = df.iloc[-1]["open_time"]
        if self.state.last_candle_ts.get(symbol) == candle_ts:
            result.update(reason="already evaluated this candle")
            return result

        # --- respect a cooldown after a failed/rejected order ---
        cd = self.state.entry_cooldown_until.get(symbol)
        if cd and datetime.now(timezone.utc) < cd:
            result.update(reason="entry cooldown active")
            return result

        # mark this candle as evaluated regardless of the outcome below
        self.state.last_candle_ts[symbol] = candle_ts

        # 5) strategy signal
        signal = self.strategy.generate(df)
        if signal is None:
            result.update(reason="no signal")
            return result

        if symbol in self.state.open_positions:
            result.update(reason="position already open")
            return result

        # 6) AI advisory score (can only block / downsize)
        assessment = self.ai.assess(signal, df)
        self._record_signal(symbol, signal, regime, assessment)
        if not assessment.allow:
            result.update(action="rejected",
                          reason=f"AI score {assessment.score} < {self.cfg.min_ai_score}")
            return result

        # 7) risk sizing + veto
        sym = self.exchange.get_symbol_info(symbol)
        decision = self.risk.evaluate(signal, acct, sym)
        if not decision.approved:
            result.update(action="rejected", reason=f"risk: {decision.reason}")
            return result

        # 8) order validation
        ok, vreason = self._validate_order(signal, decision.qty, sym)
        if not ok:
            result.update(action="rejected", reason=f"validation: {vreason}")
            return result

        # 9) execute (safe + atomic: see _execute)
        ok, why = self._execute(symbol, signal, decision.qty)
        if not ok:
            result.update(action="rejected", reason=why)
            return result
        self._alert(f"OPEN {symbol} {signal.side.value} qty {decision.qty} "
                    f"@ {signal.entry:.2f} stop {signal.stop:.2f} "
                    f"(AI {assessment.score}) — {signal.reason}")
        result.update(action="entered", reason=signal.reason, qty=decision.qty,
                      ai_score=assessment.score, side=signal.side.value,
                      entry=signal.entry, stop=signal.stop)
        return result

    # ---- helpers ----
    def _account_state(self) -> AccountState:
        bal = self.exchange.get_balance()
        daily = bal.equity - (self.state.day_start_equity or bal.equity)
        weekly = bal.equity - (self.state.week_start_equity or bal.equity)
        return AccountState(
            equity=bal.equity, open_positions=len(self.state.open_positions),
            day_start_equity=self.state.day_start_equity or bal.equity,
            daily_pnl=daily, weekly_pnl=weekly,
            consecutive_losses=self.state.consecutive_losses,
            manual_halt=self.state.halt_reason == "manual kill switch" and self.state.halted,
        )

    def _maybe_rollover_day(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.state.current_day:
            self.state.current_day = today
            self.state.day_start_equity = self.exchange.get_balance().equity

    def _validate_order(self, signal, qty, sym) -> tuple[bool, str | None]:
        if qty <= 0:
            return False, "qty <= 0"
        if qty * signal.entry < sym.min_notional:
            return False, "below min notional"
        if signal.side == Side.long and signal.stop >= signal.entry:
            return False, "long stop not below entry"
        if signal.side == Side.short and signal.stop <= signal.entry:
            return False, "short stop not above entry"
        return True, None

    # how long to pause new entries on a symbol after an order is rejected
    ENTRY_COOLDOWN = timedelta(minutes=15)

    def _execute(self, symbol: str, signal, qty: float) -> tuple[bool, str]:
        """Place the entry, then protect it — safely and atomically.

        Failure modes handled:
          * entry rejected  -> nothing opened, cooldown set, clean message (no crash).
          * entry filled but protective stop rejected -> we cannot run the position
            unprotected, so we immediately market-close it (or, if that also fails,
            raise a CRITICAL alert for manual action).
        The position is recorded the instant the entry fills, so it is always
        visible to manage_open_positions even if a later step fails.
        """
        coid = "bot-" + uuid.uuid4().hex[:18]
        entry_side = OrderSide.buy if signal.side == Side.long else OrderSide.sell

        # --- 1. entry ---
        try:
            self.exchange.place_order(OrderRequest(
                symbol=symbol, side=entry_side, type=OrderType.market, qty=qty,
                client_order_id=coid,
            ))
        except PermanentOrderError as e:
            # Unrecoverable (regulatory / permission / key / IP). Don't retry —
            # stop the bot and tell the operator exactly what to do.
            msg = str(e)
            self.state.running = False
            self.state.halted = True
            self.state.halt_reason = f"exchange blocked orders: {msg}"
            self._alert(f"TRADING STOPPED — Bybit blocked orders ({msg}). "
                        f"This is an account/region restriction, not a bug. "
                        f"Switch to MODE=paper to keep testing, or resolve it "
                        f"with Bybit (KYC/region/API permissions/IP allow-list).")
            return False, f"permanent block: {msg}"
        except Exception as e:
            self.state.entry_cooldown_until[symbol] = (
                datetime.now(timezone.utc) + self.ENTRY_COOLDOWN)
            msg = str(e).splitlines()[0][:140]
            self._alert(f"ENTRY REJECTED {symbol} {signal.side.value}: {msg}")
            return False, f"exchange rejected entry: {msg}"

        # --- 2. record the position immediately (now it's tracked/managed) ---
        self.state.open_positions[symbol] = {
            "side": signal.side, "qty": qty, "entry": signal.entry,
            "stop": signal.stop, "tp": signal.take_profit,
            "trail_mult": signal.trailing_atr_mult, "atr": signal.meta.get("atr", 0.0),
            "risk_per_unit": signal.risk_per_unit, "unrealized": 0.0,
            "opened_ts": datetime.now(timezone.utc),
        }

        # --- 3. protective stop on the exchange (real venues only) ---
        if self.exchange.supports_resting_stops:
            stop_side = OrderSide.sell if signal.side == Side.long else OrderSide.buy
            try:
                self.exchange.place_order(OrderRequest(
                    symbol=symbol, side=stop_side, type=OrderType.market, qty=qty,
                    reduce_only=True, stop_price=signal.stop,
                    client_order_id=coid + "-sl",
                ))
            except Exception as e:
                # We are now exposed with no stop — do NOT keep the position.
                msg = str(e).splitlines()[0][:140]
                try:
                    price = self.exchange.get_last_price(symbol)
                    self._close_position(symbol, price, "stop_place_failed")
                    self._alert(f"STOP FAILED {symbol}: closed immediately ({msg})")
                    return False, f"stop rejected, position closed: {msg}"
                except Exception:
                    self._alert(f"CRITICAL {symbol}: OPEN WITH NO STOP — "
                                f"close it manually NOW ({msg})")
                    return False, f"stop rejected AND auto-close failed: {msg}"
        return True, "ok"

    # ---- emergency stop ----
    def kill(self, flatten: bool = True) -> None:
        """Cancel all orders, optionally flatten, and halt. The panic button."""
        self.exchange.cancel_all()
        if flatten:
            for symbol in list(self.state.open_positions.keys()):
                price = self.exchange.get_last_price(symbol)
                self._close_position(symbol, price, "kill_switch")
        self.state.open_positions.clear()
        self.state.halted = True
        self.state.halt_reason = "manual kill switch"
        self.state.running = False
        self._alert("KILL SWITCH activated — flattened & halted.")

    # ---- optional side-effects (never crash the loop) ----
    def _alert(self, msg: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(msg)
            except Exception:
                pass

    def _record_trade(self, trade: dict) -> None:
        if self.recorder:
            try:
                self.recorder.save_trade(trade)
            except Exception:
                pass

    def _record_signal(self, symbol, signal, regime, assessment) -> None:
        if self.recorder:
            try:
                self.recorder.save_signal(symbol, signal, regime, assessment,
                                          self.timeframe)
            except Exception:
                pass


def _to_df(candles) -> pd.DataFrame:
    return pd.DataFrame([{
        "open_time": c.open_time, "open": c.open, "high": c.high,
        "low": c.low, "close": c.close, "volume": c.volume,
    } for c in candles])
