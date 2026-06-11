"""Exchange abstraction layer.

The rest of the bot talks ONLY to this interface, never to a specific exchange
SDK. That means the same strategy / risk / engine code runs identically against:
  * PaperExchange  – simulated fills (paper trading + backtests)
  * BybitExchange  – real Bybit testnet or mainnet

Swapping venues later (Binance, OKX, IBKR) means writing one new subclass.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"


class PermanentOrderError(Exception):
    """An order rejection that will NOT fix itself on retry — e.g. a regulatory
    block, disabled API permission, bad key, or IP not whitelisted. The engine
    treats this as fatal for trading: it stops the loop and tells the operator,
    instead of hammering the exchange forever."""


@dataclass
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SymbolInfo:
    symbol: str
    tick_size: float
    qty_step: float
    min_notional: float


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    type: OrderType
    qty: float
    price: float | None = None          # required for limit
    reduce_only: bool = False           # True for stops / exits
    stop_price: float | None = None     # for on-exchange stop orders
    client_order_id: str | None = None  # idempotency key


@dataclass
class OrderResult:
    client_order_id: str
    exchange_order_id: str | None
    symbol: str
    side: OrderSide
    qty: float
    status: str
    filled_qty: float = 0.0
    avg_fill_price: float | None = None
    fee: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class Balance:
    equity: float       # total account value incl. unrealized PnL
    available: float    # free margin / cash


class AbstractExchange(abc.ABC):
    """Every exchange backend implements exactly this surface."""

    name: str = "abstract"
    # True if the venue can hold a resting stop order on its own book (real
    # exchanges). False for the paper simulator, which has no order book — the
    # engine then manages stops/TPs itself by checking price each tick.
    supports_resting_stops: bool = True

    # --- market data ---
    @abc.abstractmethod
    def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        ...

    @abc.abstractmethod
    def get_last_price(self, symbol: str) -> float:
        ...

    @abc.abstractmethod
    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        ...

    # --- account ---
    @abc.abstractmethod
    def get_balance(self) -> Balance:
        ...

    # --- trading ---
    @abc.abstractmethod
    def place_order(self, req: OrderRequest) -> OrderResult:
        ...

    @abc.abstractmethod
    def cancel_all(self, symbol: str | None = None) -> None:
        ...

    @abc.abstractmethod
    def set_leverage(self, symbol: str, leverage: float) -> None:
        ...

    # --- helpers shared by all backends ---
    @staticmethod
    def round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return round(round(value / step) * step, 12)
