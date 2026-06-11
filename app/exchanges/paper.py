"""PaperExchange — simulated execution used for paper trading AND backtesting.

It pulls REAL market data from a wrapped data source (e.g. a BybitExchange in
read-only mode, or injected candles in a backtest) but FILLS orders in
simulation, applying fees, slippage and spread so that paper/backtest results
resemble reality instead of a frictionless fantasy.

Where the bot loses money in real life — fees and slippage — is modeled here on
purpose, so the numbers you see in paper are honest.
"""
from __future__ import annotations

import uuid

from app.config import get_settings
from app.exchanges.base import (
    AbstractExchange, Balance, Candle, OrderRequest, OrderResult, OrderSide,
    SymbolInfo,
)


class PaperExchange(AbstractExchange):
    name = "paper"
    supports_resting_stops = False  # no order book -> engine manages exits

    def __init__(self, data_source: AbstractExchange | None = None,
                 starting_equity: float = 10_000.0):
        """`data_source` provides real candles/prices (read-only). If None, the
        caller must feed prices via ``set_price`` (used by the backtester)."""
        self.cfg = get_settings()
        self.data_source = data_source
        self._equity = starting_equity
        self._available = starting_equity
        self._prices: dict[str, float] = {}
        # symbol -> dict(side, qty, entry) ; one netted position per symbol
        self.positions: dict[str, dict] = {}

    # ---- price feed ----
    def set_price(self, symbol: str, price: float) -> None:
        """Used by the backtester to advance the simulated 'current' price."""
        self._prices[symbol] = price

    def get_last_price(self, symbol: str) -> float:
        if self.data_source is not None:
            return self.data_source.get_last_price(symbol)
        return self._prices[symbol]

    def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        if self.data_source is None:
            raise RuntimeError("PaperExchange has no data_source for candles")
        return self.data_source.get_candles(symbol, timeframe, limit)

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        if self.data_source is not None:
            return self.data_source.get_symbol_info(symbol)
        return SymbolInfo(symbol, tick_size=0.1, qty_step=0.001, min_notional=5.0)

    # ---- account ----
    def get_balance(self) -> Balance:
        return Balance(equity=self._equity, available=self._available)

    # ---- fills ----
    def _fill_price(self, side: OrderSide, ref: float) -> float:
        """Apply spread + slippage against us (we always get the worse price)."""
        cost_bps = (self.cfg.slippage_bps + self.cfg.spread_bps) / 10_000.0
        if side == OrderSide.buy:
            return ref * (1 + cost_bps)
        return ref * (1 - cost_bps)

    def place_order(self, req: OrderRequest) -> OrderResult:
        ref = req.price if req.price else self.get_last_price(req.symbol)
        fill = self._fill_price(req.side, ref)
        fee = abs(fill * req.qty) * (self.cfg.taker_fee_bps / 10_000.0)
        self._available -= fee
        self._equity -= fee

        self._apply_to_position(req, fill)

        return OrderResult(
            client_order_id=req.client_order_id or str(uuid.uuid4()),
            exchange_order_id="paper-" + uuid.uuid4().hex[:12],
            symbol=req.symbol, side=req.side, qty=req.qty,
            status="filled", filled_qty=req.qty, avg_fill_price=fill, fee=fee,
            raw={"simulated": True},
        )

    def _apply_to_position(self, req: OrderRequest, fill: float) -> None:
        """Net the order into a per-symbol position and realize PnL on close."""
        signed = req.qty if req.side == OrderSide.buy else -req.qty
        pos = self.positions.get(req.symbol)
        if pos is None or pos["qty"] == 0:
            self.positions[req.symbol] = {"qty": signed, "entry": fill}
            return
        # same direction -> average in
        if (pos["qty"] > 0) == (signed > 0):
            total = pos["qty"] + signed
            pos["entry"] = (pos["entry"] * pos["qty"] + fill * signed) / total
            pos["qty"] = total
        else:
            # opposite -> realize PnL on the closed portion
            closing = min(abs(signed), abs(pos["qty"]))
            direction = 1 if pos["qty"] > 0 else -1
            realized = (fill - pos["entry"]) * direction * closing
            self._equity += realized
            self._available += realized
            pos["qty"] += signed
            if abs(pos["qty"]) < 1e-12:
                pos["qty"] = 0.0

    def cancel_all(self, symbol: str | None = None) -> None:
        # No resting orders in the simple paper model (fills are immediate).
        return None

    def set_leverage(self, symbol: str, leverage: float) -> None:
        return None
