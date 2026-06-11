"""FastAPI application entry point.

  uvicorn app.main:app --reload

The trading loop itself runs as a separate process (app.trading.paper_trader) so
the API stays responsive; this app exposes status + control endpoints.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Trading Bot", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
def _startup():
    cfg = get_settings()
    # Create tables if the DB is reachable; don't crash the API if it isn't
    # (useful for local poking / tests without Postgres).
    try:
        from app.db.base import init_db
        init_db()
    except Exception as e:  # pragma: no cover
        logging.warning("DB init skipped: %s", e)
    logging.info("API up | mode=%s symbols=%s", cfg.mode, cfg.symbol_list)


@app.get("/")
def root():
    return {"service": "trading-bot", "docs": "/docs"}
