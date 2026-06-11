# Quickstart — from zero to a running bot

> Default mode is **paper** (simulated money on real prices). It needs **no API
> key**. Only switch to **live** after paper looks good. Capital protection first.

## 1. Install

```bash
cd trading_bot
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. (Optional) Download history & backtest

```bash
python scripts/backfill.py --symbol BTCUSDT --timeframe 1h --bars 8000
python run_backtest.py --csv data/btcusdt_1h.csv
```

Read the metrics critically. If profit factor < 1.2, drawdown is large, or it only
works on one period, the strategy has **no reliable edge** — tune or replace it
before trading. Most simple strategies fail here. That is the system working.

## 3. Run in PAPER mode (no key needed)

`.env` already has `MODE=paper`. Just run:

```bash
python run.py
```

You'll see a preflight summary, a connectivity check, then live decisions logged
each minute (entries, exits, why trades were skipped). Let it run for **weeks** and
compare results to your backtest.

## 4. Add your API key and go LIVE (when ready)

1. On **Bybit**, create an API key:
   - Permission: **Trade** (Contract/USDT Perp). **Withdrawals: OFF.**
   - **IP allow-list: ON** (your server's IP).
   - Start with a **testnet** key (https://testnet.bybit.com).
2. Put the key in `.env` and flip the mode:

   ```ini
   MODE=live
   BYBIT_API_KEY=your_key_here
   BYBIT_API_SECRET=your_secret_here
   BYBIT_TESTNET=true        # keep true until you've proven it on testnet
   ```

3. Start it:

   ```bash
   python run.py
   ```

   In live mode the preflight verifies your keys and shows your real equity. On
   **mainnet** it forces a typed confirmation before risking real money. Begin
   with a **tiny** allocation and the default risk limits — never disable them.

## 5. Dashboard / control API (optional, one process)

```bash
uvicorn app.main:app --reload      # http://localhost:8000/docs
```

- `POST /control/start` — start the loop in a background thread
- `GET  /status`        — balance, equity, daily PnL, open positions, halts
- `GET  /positions`, `GET /trades`, `GET /risk`
- `POST /control/kill` — **emergency**: cancel orders, flatten, halt
- `POST /control/mode`  — switch paper/live (`{"mode":"live","confirm_live":true}`)

## 6. Telegram alerts (optional)

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` to get a message on
every open/close, halt, and the kill switch. Leave blank to disable.

## What "input the API key and it works" means here

- **Paper**: nothing to enter — `python run.py` trades simulated immediately.
- **Live**: set the three `BYBIT_*` values + `MODE=live` in `.env`, run `python
  run.py`. Keys are read **only** from environment variables, never logged, never
  returned by the API.

## Where it can lose money (read `ARCHITECTURE.md` §0)

Fees, slippage, regime change, overfitting, leverage, tail events. The risk
manager caps per-trade/daily/weekly losses, sizes from ATR, halts on losing
streaks, and trips a circuit breaker on abnormal moves — but **no bot guarantees
profit**. Keep the limits on. Start small.
```
