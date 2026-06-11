"""SQLAlchemy engine, session factory and declarative Base.

The engine is created LAZILY (on first use), so importing the ORM models does
NOT require a database driver or a running Postgres. That keeps backtests, paper
trading and unit tests fully usable without infrastructure. Call ``init_db()``
once at startup to create tables (MVP convenience; use Alembic in production).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url, pool_pre_ping=True, future=True
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
    return _SessionLocal


def init_db() -> None:
    from app.db import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=get_engine())


def get_session():
    """FastAPI dependency / context helper yielding a session."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
