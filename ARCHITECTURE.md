# Trading Bot — Architecture & Implementation Plan

> **Read this first.** This system is built **capital-protection first, profit second.**
> There is **no guaranteed profit.** A well-built bot with good risk management still
> loses money in many months. The realistic goal is a *positive expectancy* edge
> applied with strict risk control so that losing streaks don't blow up the account.
> Most of the engineering effort here is spent on *not losing*, not on *winning*.

Stack chosen: **Python 3.11 + FastAPI + PostgreSQL + Redis**. First exchange target:
**Bybit USDT perpetuals** (derivatives), via the official `pybit` SDK + WebSocket.

---

## 0. Honest expectations — where this bot loses money

| Source of loss | Why it happens | How this system reduces it |
|---|---|---|
| **Fees & funding** | Perps charge maker/taker fees + funding every 8h. High-frequency = fee bleed. | Fees/slippage modeled in backtest & paper; scalping disabled by default; funding-aware. |
| **Slippage** | Market orders fill worse than expected, especially in thin books / fast moves. | Slippage model in paper/backtest; liquidity filter; prefer limit entries. |
| **Overfitting** | A strategy tuned to past data fails live. | Walk-forward + out-of-sample testing; few parameters; regime filter, not curve-fit. |
| **Regime change** | Trend strategy in a chop = death by a thousand cuts. | Regime detector; bot sits out unclear conditions. |
| **Tail events / gaps** | Flash crashes, exchange outages, depeg, liquidation cascades. | Circuit breaker, max leverage cap, hard stop-loss always on exchange, daily loss limit. |
| **Execution/infra bugs** | Double orders, stale prices, partial fills, reconnect gaps. | Idempotent order IDs, order validation, paper mode first, full audit logging. |
| **Leverage** | Amplifies both sides; a 0.5% risk with 10x can still liquidate on a wick. | Leverage hard-capped; position size from ATR risk, *not* from max leverage. |
| **Psychology / over-tuning** | Operator keeps "fixing" the bot after losses. | Rules are versioned; changes require re-backtest; kill switch instead of tweaking live. |

**Rule of thumb:** if a backtest shows >100% annual return with a smooth equity curve,
it is almost certainly overfit or has look-ahead bias. Be suspicious of good results.

---

## 1. High-level architecture

```
                          ┌─────────────────────────────┐
                          │        Web Dashboard         │
                          │  (balance, PnL, positions,   │
                          │   start/stop, paper/live)    │
                          └───────────────┬──────────────┘
                                          │ REST + WS
                          ┌───────────────▼──────────────┐
                          │         FastAPI API           │
                          │  /status /positions /trades   │
                          │  /control (start/stop/kill)   │
                          └───────────────┬──────────────┘
                                          │
   ┌──────────────┐   prices   ┌──────────▼───────────┐   orders   ┌───────────────┐
   │  Market Data │──────────► │   Trading Engine     │──────────► │  Exchange     │
   │  (WS + REST) │            │  (the orchestrator)  │            │  Layer        │
   │  → Redis     │            │                      │            │  Bybit/Paper  │
   └──────────────┘            │  pipeline per tick:  │            └───────────────┘
                               │   1 fetch candles    │
   ┌──────────────┐            │   2 indicators       │            ┌───────────────┐
   │ News / Econ  │──filter──► │   3 regime filter    │ ◄──checks──│ Risk Manager  │
   │ Calendar     │            │   4 news filter      │            │ (veto power)  │
   └──────────────┘            │   5 strategy signal  │            └───────────────┘
                               │   6 AI score (0-100) │
   ┌──────────────┐            │   7 risk sizing+veto │            ┌───────────────┐
   │ AI Layer     │──score───► │   8 order validate   │──persist──►│ PostgreSQL    │
   │ (advisory)   │            │   9 execute          │            │ trades/logs   │
   └──────────────┘            └──────────┬───────────┘            └───────────────┘
                                          │ alerts
                                ┌─────────▼──────────┐
                                │ Telegram / Discord │
                                └────────────────────┘
```

**Key principle — separation of decision and authority:**
- The **Strategy** *proposes* trades (rule-based).
- The **AI layer** only *scores and explains* — it can lower conviction but **cannot create a trade**.
- The **Risk Manager** has **veto power** and final say on size; it can reject any trade.
- The **Exchange layer** only *executes* validated orders. It makes no decisions.

A trade happens only if: `strategy_signal AND regime_ok AND news_ok AND risk_ok`.
The AI score is an additional *filter that can only block or shrink*, never enable.

---

## 2. Component responsibilities

- **Market Data** — pulls OHLCV for 5m/15m/1h/4h/1d via REST (backfill) and WebSocket
  (live), normalizes, caches latest in Redis, persists candles for backtests.
- **Indicators** — pure functions on a DataFrame: EMA, RSI, MACD, Bollinger, ATR, VWAP,
  (Volume Profile as a later add-on). No state, fully unit-testable.
- **Regime detector** — classifies each symbol/timeframe as `trend_up`, `trend_down`,
  `range`, `high_vol`, `low_vol`, or `unclear`. Bot does **not** trade `unclear`.
- **Strategy engine** — pluggable strategies (trend, mean-reversion, breakout, scalping,
  DCA). Each returns a `Signal` with entry, stop, take-profit, trailing, invalidation.
- **News/Calendar filter** — blocks new entries inside a window around high-impact events
  (CPI, FOMC, NFP, rate decisions) and major crypto events (ETF, regulation, exchange news).
- **AI layer** — LLM/heuristic that summarizes conditions and outputs a 0–100 quality
  score + reasons. Advisory only.
- **Risk manager** — position sizing (ATR-based), all loss limits, max positions/leverage,
  consecutive-loss halt, circuit breaker. The gatekeeper.
- **Exchange layer** — abstract interface; Bybit (live/testnet) and Paper implementations.
- **Backtester** — event-driven replay of historical candles through the *same* strategy
  and risk code, with fees/slippage/spread, producing standard metrics.
- **Paper trader** — live data, simulated fills, identical code path to live. The dress
  rehearsal before risking real money.
- **API + Dashboard** — observe and control.

---

## 3. Database schema (PostgreSQL)

```
symbols
  id PK · exchange · symbol · base · quote · tick_size · qty_step · min_notional · active

candles                          -- OHLCV store for backtests & indicators
  id PK · symbol_id FK · timeframe · open_time(ts, idx) · open · high · low · close
  · volume · UNIQUE(symbol_id, timeframe, open_time)

signals                          -- every strategy proposal, taken or not
  id PK · ts · symbol_id FK · strategy · side · timeframe · entry · stop · take_profit
  · regime · ai_score · ai_reason(text) · risk_passed(bool) · reject_reason · raw(jsonb)

orders                           -- every order we send to an exchange
  id PK · client_order_id(uniq) · exchange_order_id · ts · symbol_id FK · side · type
  · qty · price · status · filled_qty · avg_fill_price · fee · mode(paper|live) · raw(jsonb)

trades                           -- a completed round-trip (entry→exit)
  id PK · symbol_id FK · strategy · side · mode · open_ts · close_ts
  · entry_price · exit_price · qty · gross_pnl · fees · net_pnl · r_multiple
  · stop · take_profit · exit_reason · entry_order_id FK · exit_order_id FK

positions                        -- current open exposure (1 row per open position)
  id PK · symbol_id FK · strategy · side · mode · qty · entry_price · stop · take_profit
  · trailing_stop · opened_ts · unrealized_pnl · status(open|closed)

equity_snapshots                 -- time series for the equity curve / drawdown
  id PK · ts · mode · balance · equity · open_positions · daily_pnl · drawdown

risk_state                       -- single-row-per-mode live risk accounting
  id PK · mode · day(date) · day_start_equity · daily_pnl · weekly_pnl
  · consecutive_losses · trading_halted(bool) · halt_reason · updated_ts

events                           -- economic/news calendar
  id PK · ts · kind(cpi|fomc|nfp|rate|etf|reg|exchange) · impact(low|med|high)
  · title · source · symbols(text[])

logs                             -- structured decision/audit log
  id PK · ts · level · component · message · context(jsonb)
```

Indexes: `candles(symbol_id, timeframe, open_time)`, `trades(mode, close_ts)`,
`signals(ts)`, `equity_snapshots(mode, ts)`, `logs(ts)`.

---

## 4. Folder structure

```
trading_bot/
├── ARCHITECTURE.md            ← this file
├── README.md
├── requirements.txt
├── .env.example               ← copy to .env, never commit secrets
├── docker-compose.yml         ← postgres + redis + api + worker
├── Dockerfile
├── run_backtest.py            ← CLI entry: run a backtest
├── app/
│   ├── config.py              ← pydantic settings from env vars
│   ├── main.py                ← FastAPI app
│   ├── logging_config.py
│   ├── db/
│   │   ├── base.py            ← SQLAlchemy Base + engine/session
│   │   └── models.py          ← all ORM models (schema above)
│   ├── exchanges/
│   │   ├── base.py            ← AbstractExchange interface + dataclasses
│   │   ├── bybit.py           ← Bybit live/testnet (pybit)
│   │   └── paper.py           ← PaperExchange simulator (fees/slippage/spread)
│   ├── data/
│   │   ├── indicators.py      ← EMA/RSI/MACD/BB/ATR/VWAP
│   │   ├── regime.py          ← market regime detector
│   │   └── market_data.py     ← candle fetch/backfill helpers
│   ├── strategies/
│   │   ├── base.py            ← Strategy ABC + Signal dataclass
│   │   └── ema_rsi.py         ← MVP trend strategy (EMA cross + RSI filter)
│   ├── risk/
│   │   └── risk_manager.py    ← sizing + all limits + circuit breaker
│   ├── backtest/
│   │   ├── engine.py          ← event-driven backtester
│   │   └── metrics.py         ← win rate, PF, DD, Sharpe, expectancy
│   ├── trading/
│   │   ├── paper_trader.py    ← live-data simulated execution loop
│   │   └── engine.py          ← shared per-tick pipeline (used by paper+live)
│   ├── ai/
│   │   └── analyst.py         ← advisory scoring/summary (stub + interface)
│   ├── news/
│   │   └── calendar.py        ← economic/news event filter
│   └── api/
│       └── routes.py          ← REST + control endpoints
└── tests/
    ├── test_indicators.py
    ├── test_risk.py
    └── test_backtest.py
```

The MVP delivered now implements the **bold** path: db/models, exchanges (base+bybit+paper),
data/indicators+regime, strategies/ema_rsi, risk_manager, backtest engine+metrics,
paper_trader, api, and tests. News/AI ship as clean stubs with real interfaces.

---

## 5. Strategy logic (all five, MVP ships EMA+RSI)

Every strategy returns a `Signal(side, entry, stop, take_profit, trailing_atr_mult,
invalidation, meta)` or `None`. Stops are **mandatory** — a strategy may never return a
signal without a stop.

**1. Trend-following (MVP: EMA + RSI)** — on the 1h: EMA(50) over EMA(200) = uptrend.
Enter long when price pulls back to EMA(50) and RSI(14) crosses back above 50 (momentum
resuming with trend). Stop = `entry − 2·ATR(14)`. TP = `entry + 3·ATR` (1.5R) plus a
trailing stop at `2·ATR` once +1R. Invalidation: EMA(50) crosses below EMA(200), or close
back below EMA(200).

**2. Mean-reversion** — only in `range` regime. Long when price tags lower Bollinger(20,2)
*and* RSI < 30 *and* not in a downtrend on higher TF. Exit at the mean (BB mid). Stop below
the range low. Avoid when ATR is expanding (breakout risk).

**3. Breakout** — only in `low_vol → expansion` transition. Enter on close beyond N-bar
high/low with volume > 1.5× average and ATR rising. Stop on the other side of the box.
Trail aggressively; breakouts that fail must be cut fast (`invalidation` = close back inside).

**4. Scalping** — *disabled by default.* 5m, VWAP + order-flow. Fees dominate at this
frequency; only enable with maker rebates and proven low-latency infra.

**5. DCA (strict)** — *not* averaging into losers. A planned, capped ladder of entries in a
confirmed uptrend, with a **hard total-position cap**, a **max number of adds (e.g. 3)**, and
a **single shared stop** for the whole ladder. If the shared stop is hit, the entire position
exits. No add is allowed below the shared stop.

---

## 6. Risk management rules (the core)

These are enforced in code by `RiskManager`, which has veto power over every trade.

- **Per-trade risk:** 0.5%–1.0% of account equity (configurable, default 0.5%).
- **Position size** is derived from risk, *not* leverage:
  `qty = (equity · risk_pct) / (|entry − stop|)`, then capped by max-leverage notional
  and rounded to the symbol's `qty_step`. Wider stop ⇒ smaller size automatically.
- **Daily max loss:** default 2% of day-start equity → halt new entries for the day.
- **Weekly max loss:** default 5% → halt for the week.
- **Max open positions:** default 3 (limits correlated exposure).
- **Max leverage:** hard cap (default 3x) regardless of what sizing suggests.
- **Consecutive losses:** after N (default 4) in a row → cooldown halt (e.g. 24h).
- **Circuit breaker:** if price moves > X·ATR in one candle, or spread/funding spikes
  abnormally, flatten/freeze and alert — do not trade into chaos.
- **No averaging down** except the explicit DCA ladder above with its shared stop.
- **Anti-overtrading:** min time between entries per symbol; max trades per day.
- **Stops live on the exchange** (reduce-only order) so a bot crash can't remove protection.

`RiskManager.evaluate(signal, account_state)` returns `RiskDecision(approved, qty,
reason)`. If `approved` is false, the signal is logged and dropped.

---

## 7. Backtesting engine design

Event-driven (bar-by-bar), **not** vectorized, so it uses the *exact same* strategy and
risk code as live — no logic drift.

- Feeds historical candles one bar at a time; the strategy only ever sees bars up to `t`
  (prevents look-ahead bias).
- Fills modeled with **fees** (taker bps), **slippage** (bps or ATR-fraction), and
  **spread**. Stops/TPs checked intrabar with conservative assumptions (stop assumed hit
  before TP if both touched in the same bar).
- Tracks equity curve, applies the real `RiskManager` for sizing and halts.
- **Metrics:** total/CAGR return, win rate, profit factor, max drawdown, Sharpe & Sortino,
  average R-multiple, expectancy, exposure, number of trades, fee drag.
- **Anti-overfit discipline:** keep parameters few; split data into in-sample / out-of-sample;
  walk-forward windows; test bull / bear / sideways / crash segments separately; require the
  edge to survive realistic fees. Prefer a *robust mediocre* result over a *fragile great* one.

---

## 8. Paper trading module

Same `TradingEngine` pipeline as live, but the injected exchange is `PaperExchange`:
live market data in, simulated fills out (with the same fee/slippage model as the
backtester). Every order and trade is persisted with `mode='paper'`. Daily/weekly reports
compare expected vs actual fill prices and report the metric suite. **Run paper for weeks
and require it to match backtest expectations before going live.**

---

## 9. Live trading module

- Exchange API keys come **only** from environment variables; never logged, never returned
  by the API. `.env` is git-ignored.
- Start on **Bybit testnet**, then a tiny real allocation.
- **Order validation** before every send: notional ≥ min, qty within step, price within
  bounds, leverage ≤ cap, risk approved, not halted, not in a news window.
- **Idempotency:** client-generated `client_order_id` prevents duplicate orders on retry.
- **Stops on-exchange** as reduce-only orders.
- **Emergency stop / kill switch:** `POST /control/kill` cancels all open orders, optionally
  flattens positions, and sets `trading_halted=true`. Reachable from the dashboard.
- Full structured logging of every decision (signal → checks → order → fill).

---

## 10. AI layer (advisory only — cannot trade)

Interface `AIAnalyst.assess(context) -> AIAssessment(score 0-100, summary, risks, allow)`.
It can **only**: summarize the market, score trade quality, explain allow/reject, flag risky
conditions, and write reports. The engine uses the score **only to filter or downsize**, e.g.
skip trades scoring < 55. It can never originate or enlarge a trade. The rule-based strategy
+ risk engine remain the sole source of trading authority.

---

## 11. Backend & deployment

- **API:** FastAPI (async). **Worker:** the trading loop runs as a separate process/Celery
  beat or a simple asyncio scheduler (MVP uses an asyncio loop).
- **PostgreSQL:** trades/signals/logs/candles. **Redis:** latest prices, locks, rate limits.
- **Docker Compose** for local (postgres + redis + api + worker). One `Dockerfile`.
- **Cloud:** a single small VPS is plenty and cheap — **Hetzner** (best price/perf) or
  **Railway/Render** for zero-ops. Keep the bot close to the exchange region to cut latency.
  AWS/GCP are fine but overkill for one bot.
- **Monitoring/alerts:** Telegram or Discord webhook for fills, halts, circuit-breaker,
  errors, daily report. Health endpoint + uptime check. Log to stdout + DB.

---

## 12. API endpoints

```
GET  /health
GET  /status                 → mode, running, halted, balance, equity, daily_pnl, drawdown
GET  /positions              → open positions
GET  /trades?mode=&limit=    → trade history
GET  /signals?limit=         → recent signals (taken & rejected, with reasons)
GET  /risk                   → current risk_state (limits, consecutive losses, halts)
GET  /equity?mode=           → equity curve points
POST /control/start          → start the trading loop
POST /control/stop           → stop the loop (no new entries)
POST /control/kill           → EMERGENCY: cancel orders, optional flatten, halt
POST /control/mode           → switch paper|live (live requires explicit confirm flag)
POST /backtest               → run a backtest (symbol, tf, range, strategy) → metrics
```

---

## 13. Security rules

- Secrets only in env vars / a secrets manager; `.env` git-ignored; never logged or echoed.
- API-key scope on the exchange limited to **trade**, with **withdrawals disabled** and
  IP allow-listing on.
- Dashboard/API behind auth (token) and not exposed publicly without TLS.
- Separate keys for testnet vs live; live key only on the production host.
- Validate and clamp every external input; rate-limit control endpoints.
- Principle of least privilege for DB users; backups of the trades DB.

---

## 14. Development roadmap

1. **Foundations (this MVP):** scaffold, DB models, exchange abstraction (Bybit+Paper),
   indicators+regime, EMA/RSI strategy, risk manager, backtester, paper trader, API, tests.
2. **Validate the edge:** backfill data, backtest across bull/bear/sideways/crash, walk-forward.
   Kill the strategy if it has no edge after fees. (Most candidate strategies die here — good.)
3. **Paper trading:** run live-data paper for several weeks; reconcile vs backtest.
4. **News + AI filters:** wire real economic calendar + AI scoring as *blockers only*.
5. **Live (testnet → tiny real):** on-exchange stops, kill switch, alerts, monitoring.
6. **Dashboard:** the web UI (can be a thin React/HTML client on the API).
7. **More strategies & portfolio:** add mean-reversion/breakout, correlation-aware sizing.
8. **Hardening:** reconnect logic, idempotency tests, chaos testing, runbooks.

---

## 15. Testing plan

- **Unit:** indicators vs known values; risk sizing & every limit; regime classification.
- **Integration:** backtest end-to-end on synthetic + real data; paper loop with a mock
  exchange; order-validation rejects bad orders.
- **Property/edge:** zero/negative balance, stop == entry, halted state, partial fills,
  reconnect gaps, duplicate order IDs (idempotency).
- **Backtest hygiene:** assert no look-ahead (strategy sees only past bars); fee sensitivity.
- **Pre-live checklist:** testnet dry run, kill-switch drill, alert delivery, key scoping.
```
