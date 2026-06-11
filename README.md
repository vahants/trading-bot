# Trading Bot (MVP)

A **capital-protection-first** automated trading bot for Bybit USDT perpetuals.
Python + FastAPI + PostgreSQL + Redis. Built for low, realistic returns with
strict risk management — **not** guaranteed profit. Read `ARCHITECTURE.md` first,
especially §0 (where the bot loses money) and §6 (risk rules).

## What's in this MVP

- **DB models** (`app/db/models.py`) — trades, orders, signals, positions, equity, risk state, logs.
- **Exchange layer** (`app/exchanges/`) — abstract interface + Bybit (live/testnet) + Paper simulator.
- **Indicators & regime** (`app/data/`) — EMA, RSI, MACD, Bollinger, ATR, VWAP + regime detector.
- **Strategy** (`app/strategies/ema_rsi.py`) — EMA trend filter + RSI pullback entry, ATR stops/targets.
- **Risk manager** (`app/risk/risk_manager.py`) — ATR sizing, daily/weekly limits, max positions,
  leverage cap, consecutive-loss halt, circuit breaker. Has veto power.
- **Backtester** (`app/backtest/`) — event-driven, fees+slippage, full metric suite.
- **Paper trader** (`app/trading/paper_trader.py`) — same pipeline as live, simulated fills.
- **AI layer** (`app/ai/analyst.py`) — advisory scoring ONLY; cannot create trades.
- **News filter** (`app/news/calendar.py`) — blocks entries around high-impact events.
- **API** (`app/api/routes.py`) — status, positions, control, **kill switch**, backtest.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in TESTNET keys; keep MODE=paper

# run the tests
pytest -q

# backtest on a CSV (open_time,open,high,low,close,volume)
python run_backtest.py --csv data/btc_1h.csv

# or with Docker (postgres + redis + api + worker)
docker compose up --build
```

API docs at `http://localhost:8000/docs`. Start the loop with
`POST /control/start`; panic with `POST /control/kill`.

## Safety checklist before live

1. Backtest across bull / bear / sideways / crash; survive fees; check out-of-sample.
2. Paper trade for **weeks**; reconcile vs backtest.
3. Bybit **testnet** with on-exchange stops + kill-switch drill.
4. API key: trade-only scope, **withdrawals disabled**, IP allow-list.
5. Start live with a tiny allocation. Never disable the risk limits.

There is no guaranteed profit. Most simple strategies have no edge after fees —
that's what the backtester is for. Capital protection first, profit second.
