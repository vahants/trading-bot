"""Event-driven backtester.

Bar-by-bar replay so the strategy only ever sees PAST data (no look-ahead). It
uses the SAME RiskManager that live trading uses, and the SAME fee/slippage model
as paper trading, so backtest results don't lie about costs.

Intrabar fill rules (conservative):
  * If both stop and take-profit are inside a bar's range, assume the STOP hit
    first (pessimistic — never flatters the result).
  * Entries fill at the signal bar's close +/- slippage+spread.

This is a single-symbol, single-position backtester — enough to validate an edge.
Portfolio-level backtesting (correlations, shared risk budget) is a later step.
"""
from __future__ import annotations

import pandas as pd

from app.config import get_settings
from app.data.indicators import add_indicators
from app.data.regime import classify, TRADEABLE
from app.db.models import Side
from app.risk.risk_manager import AccountState, RiskManager
from app.strategies.base import Strategy
from app.backtest.metrics import compute_metrics, BacktestMetrics


class Backtester:
    def __init__(self, strategy: Strategy, starting_equity: float = 10_000.0,
                 use_regime_filter: bool = True, settings=None):
        self.cfg = settings or get_settings()
        self.strategy = strategy
        self.start_equity = starting_equity
        self.use_regime_filter = use_regime_filter
        self.risk = RiskManager(self.cfg)

    def run(self, df: pd.DataFrame, symbol: str = "BTCUSDT",
            qty_step: float = 0.001, min_notional: float = 5.0) -> dict:
        df = add_indicators(df).reset_index(drop=True)
        cost_bps = (self.cfg.slippage_bps + self.cfg.spread_bps) / 10_000.0
        fee_bps = self.cfg.taker_fee_bps / 10_000.0

        equity = self.start_equity
        day_start_equity = equity
        equity_curve: list[float] = [equity]
        trades: list[dict] = []
        consecutive_losses = 0
        pos: dict | None = None   # open position

        from app.exchanges.base import SymbolInfo
        sym = SymbolInfo(symbol, tick_size=0.1, qty_step=qty_step, min_notional=min_notional)

        for i in range(200, len(df)):
            window = df.iloc[: i + 1]
            bar = df.iloc[i]

            # ---- manage open position first ----
            if pos is not None:
                exit_price, reason = self._check_exit(pos, bar)
                if exit_price is not None:
                    equity, trade = self._close(pos, exit_price, reason, fee_bps, equity)
                    trades.append(trade)
                    consecutive_losses = consecutive_losses + 1 if trade["net_pnl"] < 0 else 0
                    pos = None

            equity_curve.append(equity)

            if pos is not None:
                continue  # one position at a time

            # ---- look for a new entry ----
            regime = classify(window)           # always computed (for tagging)
            if self.use_regime_filter and \
                    regime not in TRADEABLE.get(self.strategy.family, set()):
                continue

            signal = self.strategy.generate(window)
            if signal is None:
                continue

            acct = AccountState(
                equity=equity, open_positions=0, day_start_equity=day_start_equity,
                daily_pnl=0.0, weekly_pnl=0.0, consecutive_losses=consecutive_losses,
            )
            decision = self.risk.evaluate(signal, acct, sym)
            if not decision.approved:
                continue

            # fill entry with costs against us
            fill = signal.entry * (1 + cost_bps) if signal.side == Side.long \
                else signal.entry * (1 - cost_bps)
            entry_fee = fill * decision.qty * fee_bps
            equity -= entry_fee
            pos = {
                "side": signal.side, "entry": fill, "qty": decision.qty,
                "stop": signal.stop, "tp": signal.take_profit,
                "risk_per_unit": signal.risk_per_unit, "entry_fee": entry_fee,
                "trail_mult": signal.trailing_atr_mult, "atr": signal.meta.get("atr", 0),
                "regime": regime, "entry_time": bar["open_time"],
            }

        metrics: BacktestMetrics = compute_metrics(trades, equity_curve, self.start_equity)
        return {
            "symbol": symbol, "strategy": self.strategy.name,
            "metrics": metrics.as_dict(), "final_equity": equity,
            "num_trades": len(trades), "trades": trades,
        }

    # ---- exit logic ----
    def _check_exit(self, pos: dict, bar) -> tuple[float | None, str | None]:
        high, low = bar["high"], bar["low"]
        # update trailing stop
        if pos["trail_mult"] and pos["atr"]:
            if pos["side"] == Side.long:
                trail = bar["close"] - pos["trail_mult"] * pos["atr"]
                pos["stop"] = max(pos["stop"], trail)
            else:
                trail = bar["close"] + pos["trail_mult"] * pos["atr"]
                pos["stop"] = min(pos["stop"], trail)

        if pos["side"] == Side.long:
            if low <= pos["stop"]:           # stop assumed first (pessimistic)
                return pos["stop"], "stop"
            if pos["tp"] and high >= pos["tp"]:
                return pos["tp"], "take_profit"
        else:
            if high >= pos["stop"]:
                return pos["stop"], "stop"
            if pos["tp"] and low <= pos["tp"]:
                return pos["tp"], "take_profit"
        return None, None

    def _close(self, pos: dict, exit_price: float, reason: str, fee_bps: float,
               equity: float):
        direction = 1 if pos["side"] == Side.long else -1
        gross = (exit_price - pos["entry"]) * direction * pos["qty"]
        exit_fee = exit_price * pos["qty"] * fee_bps
        net = gross - exit_fee  # entry fee already deducted from equity
        equity += net
        r_mult = (gross / (pos["risk_per_unit"] * pos["qty"])
                  if pos["risk_per_unit"] > 0 else None)
        trade = {
            "side": pos["side"].value, "entry_price": pos["entry"],
            "exit_price": exit_price, "qty": pos["qty"], "gross_pnl": gross,
            "fees": pos["entry_fee"] + exit_fee, "net_pnl": net,
            "r_multiple": r_mult, "exit_reason": reason,
            "regime": pos.get("regime"), "entry_time": pos.get("entry_time"),
        }
        return equity, trade
