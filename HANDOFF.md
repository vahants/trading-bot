# Project Handoff & Context

> Purpose: let anyone — a teammate, or a fresh Claude/AI session — pick this project
> up with full context. Read this first, then `ARCHITECTURE.md`, then `QUICKSTART.md`.
> Keep this file updated as the project evolves.

Last updated: 2026-06-11

---

## 0. Goal & vision (the "why")

**Mission:** a fully autonomous trading bot that runs 24/7, makes its own entry and
exit decisions from rules (no human clicking), grows the account over time, and — above
all — protects capital. It should analyze the market across timeframes, decide and size
trades by risk, place/manage/exit orders automatically, log every decision, report its
own performance, and **get better over time by learning from its own history.**

**What "maximize profit" means here (read this carefully):** the target is to maximize
*risk-adjusted* return — profit factor, expectancy, Sharpe — **under hard capital-
protection limits**, NOT raw profit at any cost. A bot that chases maximum profit with
big size and leverage eventually blows up; that is the single most common way these
projects die. The realistic aim is a small, consistent, *positive expectancy* edge that
compounds and survives drawdowns. Slow and alive beats fast and broke.

**Definition of success:** positive expectancy and profit factor > ~1.2 **net of fees**,
holding across bull / bear / sideways / crash regimes, with drawdown inside the configured
limits, validated *out-of-sample* and in *paper* before any live capital. If it can't beat
fees in honest backtests, the strategy is killed — that's the system working, not failing.

**Non-goals:** get-rich-quick, high-leverage gambling, "guaranteed" returns, or optimizing
a strategy until it looks perfect on past data (that's overfitting, and it loses live).

---

## 1. What this is

A capital-protection-first automated crypto trading bot (Bybit USDT perpetuals).
Python + FastAPI + PostgreSQL + Redis. Goal: low, realistic, risk-managed returns —
**not** guaranteed profit. The whole design prioritizes *not losing* over winning.

Stack & entry points:
- `run.py` — start the bot (reads `MODE` from `.env`).
- `app/trading/runner.py` — the live/paper loop. `app/trading/engine.py` — the per-tick decision pipeline.
- `app/exchanges/` — `base.py` (interface), `bybit.py` (real), `paper.py` (simulated).
- `app/strategies/ema_rsi.py` — the only strategy so far (EMA trend + RSI pullback).
- `app/risk/risk_manager.py` — sizing + all loss limits + circuit breaker (has veto power).
- `app/backtest/` — event-driven backtester + metrics.
- `scripts/` — `backfill.py` (download history), `report.py` (performance report), `check_keys.py`.
- `data/trades.csv`, `data/equity.csv` — auto-written results journal (survives restarts).

---

## 2. Current status (as of last update)

- ✅ Code complete for an MVP: data → indicators → regime → news → strategy → AI score
  → risk sizing/veto → safe execution. 25 unit tests passing (`pytest -q`).
- ✅ **Paper mode works** end to end (simulated fills on real Bybit prices).
- ⛔ **Live mode is blocked by Bybit, not by code.** Bybit returns `ErrCode 10024`
  ("regulatory restrictions") for this account/region — it cannot place derivatives
  orders, even on testnet. The bot now detects this and **stops cleanly** with a clear
  message instead of retrying forever. Resolving it is a Bybit account matter (KYC /
  region / permitted venue), not a code change.
- 🔜 The included EMA+RSI strategy is an **unvalidated baseline**. Its real edge after
  fees is unproven — that's what backtesting + paper trading are for.

**To run right now:** set `MODE=paper` in `.env`, then `python run.py`.
**To see results:** `python scripts/report.py` (or `--days 10`).

---

## 3. Key decisions & fixes made (changelog)

- Python 3.9 compatibility: ORM models use `Optional[...]` (not `X | None`) so the
  project runs on 3.9–3.12.
- Network resilience: Bybit client uses 30s timeout + auto-retries; transient timeouts
  log as quiet one-liners, not tracebacks.
- **Overtrading fix:** entries are decided once per *new candle* (not every 60s poll),
  with a cooldown after any rejection — stops duplicate-order storms.
- **Safe execution:** position is recorded the instant the entry fills; if the
  protective stop fails, the position is auto-closed; order errors never crash the loop.
- **Permanent-error handling:** regulatory/permission/key/IP rejections (e.g. 10024)
  stop the bot with a clear message instead of looping.
- Bybit correctness: `min_notional` now reads `minNotionalValue` (was wrongly using a
  quantity); qty/price are rounded to the symbol's step/tick to avoid live rejections.
- Results journal: every closed trade + equity snapshot written to `data/*.csv` so a
  multi-day run survives restarts with no database. `scripts/report.py` reads them.
- `pycryptodome` added (pybit needs it); scripts add the project root to `sys.path`.

---

## 4. Known issues & gotchas

- **Run from ONE permanent folder**, not the macOS Trash or scattered copies. Stale
  copies caused repeated "already-fixed" bugs to reappear. Git solves this (see §5).
- **`.env` is git-ignored** (holds API keys). After every `git clone`, recreate `.env`
  from `.env.example`. Keys live ONLY in `.env`, never in the repo.
- **24/7 needs an always-on host.** On a laptop the bot stops when it sleeps/closes/
  restarts. The on-exchange stop still protects an open position, but trailing/TP/new
  entries pause. For real use, deploy to a small VPS (Hetzner/Railway/Render) with the
  included `docker-compose.yml`.
- **Restart reconciliation not implemented.** After a restart the bot doesn't re-adopt a
  position it opened before; the exchange stop guards it, but the bot won't manage its
  TP/trailing. (On the backlog.)
- PostgreSQL is optional; without it you get a harmless "Recorder disabled" warning and
  results still go to the CSV journal.

---

## 5. Preserving history & continuing later

**Code history → Git/GitHub.** From the project folder on your Mac:
```bash
rm -rf .git                 # if a broken .git exists
git init
git add -A
git status                  # confirm .env is NOT listed
git commit -m "Trading bot MVP - paper/live, risk manager, safe execution, journal"
git branch -M main
git remote add origin https://github.com/vahants/trading-bot.git   # your repo
git push -u origin main
```
After that: `git clone` on any machine/VPS, `git pull` to sync, `git log` for full history.

**Context for a new AI session/model.** Open this project folder in Cowork (or point the
new session at it) and ask it to read `HANDOFF.md`, `ARCHITECTURE.md`, and `README.md`.
Those three files contain the full state, design, and rationale — enough to continue
without this chat. Keep this file updated (add a line under §3 whenever you change
something significant) and commit it, so the history travels with the code.

---

## 6. Backlog / next steps

1. **Validate the edge (tooling READY):** `scripts/backfill.py` to download history, then
   `scripts/validate.py` runs **walk-forward out-of-sample** validation and prints a verdict
   (edge / marginal / overfit / no edge) with regime & exit-reason breakdowns. See
   `VALIDATE.md`. This is the gate before paper/live; reject the strategy if no OOS edge
   after fees. (`run_backtest.py` is the quick single-shot backtest.)
2. **Paper-trade for weeks** in `MODE=paper`; check `scripts/report.py`; compare to backtest.
3. **Resolve live access** with Bybit (10024) OR choose a venue permitted in your region.
4. Restart-safe position reconciliation (adopt open exchange positions on startup).
5. Web dashboard on top of the existing API endpoints.
6. Telegram/daily summary alerts; VPS deploy guide; 24/7 hardening.
7. More strategies — DONE: registry with `ema_rsi`, `donchian` (breakout), `bb_meanrev`
   (range mean-reversion). Pick via `STRATEGY=` in .env (the bot runs it) and test any
   with `python scripts/validate.py --csv <file> --strategy <name|all>`. `all` prints a
   comparison table. Add new ones in `app/strategies/registry.py`. Still TODO: portfolio-
   level risk across symbols.
   NOTE (2026-06-13): `ema_rsi` validated NO EDGE on BTC 1h (OOS PF 0.77). Test the new
   strategies and higher timeframes (backfill --timeframe 4h) before trusting anything.

---

## 7. Continuous improvement & learning loop (how it gets more profitable)

The bot improves not by magic but by a disciplined feedback loop over its own recorded
history. **Everything needed to learn is already captured:** every signal (taken or
rejected, with the reason, regime, and AI score), every order, every closed trade
(entry, exit, PnL, R-multiple, exit reason), and the equity curve. Sources:
`data/trades.csv`, `data/equity.csv`, and — if Postgres is enabled — the `signals`,
`orders`, `trades`, `equity_snapshots` tables. **Keep this data** (commit periodic
snapshots, or run Postgres on the VPS); it is the dataset we learn from.

**The improvement cycle — Observe → Diagnose → Hypothesize → Backtest → Paper → Promote:**

1. **Observe.** Run `python scripts/report.py`. Look at win rate, profit factor,
   expectancy, drawdown, and the losers in `data/trades.csv`.
2. **Diagnose.** For each loss, ask *why*: stop too tight? entered in chop the regime
   filter should have caught? slippage/fees ate the edge? loss clustered around news or a
   specific regime/time? Tag the patterns — that's where the edge is leaking.
3. **Hypothesize ONE change.** A parameter (e.g. ATR stop multiple, RSI thresholds,
   `MIN_AI_SCORE`) or one rule. One variable at a time, so you can attribute the effect.
4. **Backtest it — honestly.** `run_backtest.py` on history, but the result only counts
   if it holds **out-of-sample** (data the change wasn't tuned on) and across bull / bear /
   sideways / crash, **net of fees**. A change that only helps in-sample is overfitting —
   discard it.
5. **Paper-trade it** for weeks (`MODE=paper`); confirm live-data results match the
   backtest. Reconcile differences (slippage, fills).
6. **Promote** to live only if it survives 4–5. Commit it in git with a note in §3 so you
   can **roll back** if it underperforms. Every change is versioned and reversible.

**Where ML / "training a model" fits — and the honest caveat.** You *can* train models on
this history, but naive ML on price/trade data **overfits and usually loses money live** —
this is the most common, most expensive mistake in algo trading. If/when ML is used it must:
(a) act only as a *filter or score* on rule-based signals (like the current advisory AI
layer), never as the thing that originates or sizes a trade; (b) be trained with
**walk-forward validation**, never a single train/test split; (c) be judged **net of fees**
on out-of-sample data; (d) keep the rule engine + `RiskManager` in final control. The
journaled signals+trades are the training/validation dataset for exactly this.

**Guardrails that keep "improvement" real, not self-deception:** few parameters; change one
thing at a time; out-of-sample + walk-forward always; segment results by regime; keep a
strategy changelog in git; **never disable the risk limits to chase returns.** Improvement
means a more robust edge, not a prettier backtest.

---

There is no guaranteed profit. Capital protection first, profit second. Improvement is a
slow, evidence-based loop — measured in months of validated changes, not overnight wins.
