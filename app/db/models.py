"""ORM models — the persistence layer described in ARCHITECTURE.md §3.

Everything the bot does is recorded: every signal (taken or rejected), every
order, every completed trade, the equity curve, and a single-row risk state per
mode. This audit trail is what lets you trust (or debug) the bot.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


# ---------- enums ----------
class Side(str, enum.Enum):
    long = "long"
    short = "short"


class OrderStatus(str, enum.Enum):
    new = "new"
    submitted = "submitted"
    filled = "filled"
    partially_filled = "partially_filled"
    cancelled = "cancelled"
    rejected = "rejected"


class Mode(str, enum.Enum):
    paper = "paper"
    live = "live"
    backtest = "backtest"


# ---------- reference ----------
class Symbol(Base):
    __tablename__ = "symbols"
    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), default="bybit")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    base: Mapped[str] = mapped_column(String(16))
    quote: Mapped[str] = mapped_column(String(16))
    tick_size: Mapped[float] = mapped_column(Float, default=0.1)
    qty_step: Mapped[float] = mapped_column(Float, default=0.001)
    min_notional: Mapped[float] = mapped_column(Float, default=5.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("exchange", "symbol"),)


class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))  # "5m","1h",...
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("symbol_id", "timeframe", "open_time"),
        Index("ix_candles_lookup", "symbol_id", "timeframe", "open_time"),
    )


# ---------- decisions ----------
class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(48))
    side: Mapped[Side] = mapped_column(Enum(Side))
    timeframe: Mapped[str] = mapped_column(String(8))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    ai_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[Side] = mapped_column(Enum(Side))
    type: Mapped[str] = mapped_column(String(16))  # market | limit | stop
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.new)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[Mode] = mapped_column(Enum(Mode), default=Mode.paper)
    raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(48))
    side: Mapped[Side] = mapped_column(Enum(Side))
    mode: Mapped[Mode] = mapped_column(Enum(Mode), default=Mode.paper)
    open_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    close_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty: Mapped[float] = mapped_column(Float)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    r_multiple: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(48))
    side: Mapped[Side] = mapped_column(Enum(Side))
    mode: Mapped[Mode] = mapped_column(Enum(Mode), default=Mode.paper)
    qty: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    mode: Mapped[Mode] = mapped_column(Enum(Mode), default=Mode.paper)
    balance: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    daily_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)


class RiskState(Base):
    __tablename__ = "risk_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[Mode] = mapped_column(Enum(Mode), default=Mode.paper)
    day: Mapped[date] = mapped_column(Date)
    day_start_equity: Mapped[float] = mapped_column(Float)
    daily_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    trading_halted: Mapped[bool] = mapped_column(Boolean, default=False)
    halt_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(24))   # cpi|fomc|nfp|rate|etf|reg|exchange
    impact: Mapped[str] = mapped_column(String(8))  # low|med|high
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class LogRow(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    level: Mapped[str] = mapped_column(String(8), default="info")
    component: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
