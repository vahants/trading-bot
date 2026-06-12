"""BybitExchange — real Bybit v5 integration (USDT perpetuals / "linear").

Uses the official `pybit` SDK. Keys come ONLY from environment variables via
config; they are never logged. Start on TESTNET (BYBIT_TESTNET=true).

This class is import-safe even if `pybit` isn't installed: the import is lazy so
the rest of the project (paper trading, backtests, tests) works without it.
"""
from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone

from app.config import get_settings
from app.exchanges.base import (
    AbstractExchange, Balance, Candle, OrderRequest, OrderResult, OrderSide,
    OrderType, PermanentOrderError, SymbolInfo, TransientExchangeError,
)

# Bybit kline interval codes (minutes, or D/W).
_TF_MAP = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

# Bybit retCodes that won't fix themselves on retry → treat as fatal for trading.
#  10003 invalid api key · 10004 sign error · 10005 permission denied
#  10010 unmatched IP / not whitelisted · 10024 regulatory restriction
_PERMANENT_CODES = {10003, 10004, 10005, 10010, 10024}
_PERMANENT_HINTS = ("10024", "regulatory", "10005", "permission denied",
                    "10010", "unmatched IP", "10003", "invalid api key")


class BybitExchange(AbstractExchange):
    name = "bybit"

    def __init__(self, testnet: bool | None = None):
        # `testnet=None` follows config. Pass testnet=False to read REAL mainnet
        # market data (public, no key) — used by paper mode for realistic prices.
        self.cfg = get_settings()
        self.category = self.cfg.bybit_category
        self._testnet = self.cfg.bybit_testnet if testnet is None else testnet
        self._client = None  # lazy
        self._symbol_cache: dict[str, SymbolInfo] = {}
        # Short candle cache cuts repeated /market/kline calls (rate-limit relief).
        # 90s is fine for a 15m+ strategy; exits still use the live ticker price.
        self._candle_cache: dict = {}
        self._candle_ttl = 90.0

    # ---- lazy client so the package imports without pybit / keys ----
    @property
    def client(self):
        if self._client is None:
            from pybit.unified_trading import HTTP  # imported only when needed

            self._client = HTTP(
                testnet=self._testnet,
                api_key=self.cfg.bybit_api_key,
                api_secret=self.cfg.bybit_api_secret,
                timeout=30,          # testnet is slow; 10s default times out
                max_retries=3,       # auto-retry transient failures
                retry_delay=3,
                force_retry=True,    # retry on network errors / timeouts too
                recv_window=10000,   # tolerate clock skew between you and Bybit
            )
        return self._client

    def _guard(self, fn, *args, **kwargs):
        """Run a pybit call, converting rate-limit / SDK quirks into a clean
        TransientExchangeError the loop can shrug off and retry next cycle."""
        try:
            return fn(*args, **kwargs)
        except KeyError as e:
            # pybit's own rate-limit handler crashes reading a header that Bybit
            # didn't send (X-Bapi-Limit-Reset-Timestamp). Treat as transient.
            raise TransientExchangeError(f"rate-limit/SDK header issue: {e}") from e
        except Exception as e:
            code = getattr(e, "status_code", None)
            text = str(e)
            if code == 10006 or "10006" in text or "rate limit" in text.lower():
                raise TransientExchangeError(
                    f"rate limited: {text.splitlines()[0][:120]}") from e
            raise

    # ---- market data ----
    def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        key = (symbol, timeframe, limit)
        hit = self._candle_cache.get(key)
        if hit and (time.monotonic() - hit[0]) < self._candle_ttl:
            return hit[1]
        interval = _TF_MAP[timeframe]
        resp = self._guard(
            self.client.get_kline,
            category=self.category, symbol=symbol, interval=interval, limit=limit,
        )
        rows = resp["result"]["list"]  # newest first
        candles = []
        for r in reversed(rows):  # chronological
            candles.append(Candle(
                open_time=datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc),
                open=float(r[1]), high=float(r[2]), low=float(r[3]),
                close=float(r[4]), volume=float(r[5]),
            ))
        self._candle_cache[key] = (time.monotonic(), candles)
        return candles

    def get_last_price(self, symbol: str) -> float:
        resp = self._guard(self.client.get_tickers,
                           category=self.category, symbol=symbol)
        return float(resp["result"]["list"][0]["lastPrice"])

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]
        resp = self._guard(self.client.get_instruments_info,
                           category=self.category, symbol=symbol)
        it = resp["result"]["list"][0]
        lot = it["lotSizeFilter"]
        # minNotionalValue is the USD minimum (what we need). minOrderQty is a
        # QUANTITY, not a dollar amount — using it here was a bug.
        min_notional = float(lot.get("minNotionalValue", 0) or 0) or 5.0
        info = SymbolInfo(
            symbol=symbol,
            tick_size=float(it["priceFilter"]["tickSize"]),
            qty_step=float(lot["qtyStep"]),
            min_notional=min_notional,
        )
        self._symbol_cache[symbol] = info
        return info

    @staticmethod
    def _fmt(value: float, step: float, floor: bool = False) -> str:
        """Quantize `value` to `step` and return a clean string Bybit accepts
        (no float artifacts, correct precision). Floor for quantities so we never
        size above what risk approved; round-to-nearest for prices."""
        if step and step > 0:
            n = value / step
            n = math.floor(n) if floor else round(n)
            value = n * step
        s = f"{value:.10f}".rstrip("0").rstrip(".")
        return s if s else "0"

    # ---- account ----
    def get_balance(self) -> Balance:
        resp = self._guard(self.client.get_wallet_balance, accountType="UNIFIED")
        acct = resp["result"]["list"][0]
        equity = float(acct.get("totalEquity", 0) or 0)
        available = float(acct.get("totalAvailableBalance", 0) or 0)
        return Balance(equity=equity, available=available)

    # ---- trading ----
    def place_order(self, req: OrderRequest) -> OrderResult:
        coid = req.client_order_id or ("bot-" + uuid.uuid4().hex[:20])
        info = self.get_symbol_info(req.symbol)  # cached
        params = dict(
            category=self.category,
            symbol=req.symbol,
            side="Buy" if req.side == OrderSide.buy else "Sell",
            orderType="Market" if req.type == OrderType.market else "Limit",
            qty=self._fmt(req.qty, info.qty_step, floor=True),
            reduceOnly=req.reduce_only,
            orderLinkId=coid,           # idempotency: Bybit rejects duplicates
        )
        if req.type == OrderType.limit and req.price is not None:
            params["price"] = self._fmt(req.price, info.tick_size)
        if req.stop_price is not None:
            params["triggerPrice"] = self._fmt(req.stop_price, info.tick_size)
            params["triggerDirection"] = 2 if req.side == OrderSide.sell else 1

        try:
            resp = self.client.place_order(**params)
        except Exception as e:
            # Classify unrecoverable rejections so the engine can stop cleanly
            # instead of retrying forever (regulatory block, bad key/permission,
            # IP not whitelisted). status_code is Bybit's retCode when present.
            code = getattr(e, "status_code", None)
            text = str(e)
            if code in _PERMANENT_CODES or any(s in text for s in _PERMANENT_HINTS):
                raise PermanentOrderError(text.splitlines()[0][:160]) from e
            raise
        oid = resp.get("result", {}).get("orderId")
        return OrderResult(
            client_order_id=coid, exchange_order_id=oid, symbol=req.symbol,
            side=req.side, qty=req.qty, status="submitted", raw=resp,
        )

    def cancel_all(self, symbol: str | None = None) -> None:
        params = {"category": self.category}
        if symbol:
            params["symbol"] = symbol
        self.client.cancel_all_orders(**params)

    def set_leverage(self, symbol: str, leverage: float) -> None:
        try:
            self.client.set_leverage(
                category=self.category, symbol=symbol,
                buyLeverage=str(leverage), sellLeverage=str(leverage),
            )
        except Exception:
            # Bybit errors if leverage is already set to the same value — ignore.
            pass
