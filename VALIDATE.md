# How to validate a strategy (before trusting it with money)

The golden rule: **a strategy is worthless until it survives out-of-sample testing
net of fees.** A normal backtest tunes and tests on the same data — it almost always
looks good and almost always fails live. Walk-forward is the honest test.

## Run it

```bash
# 1. get real history (more bars = more reliable; aim for 1-2 years)
python scripts/backfill.py --symbol BTCUSDT --timeframe 1h --bars 12000

# 2. validate
python scripts/validate.py --csv data/btcusdt_1h.csv
```

## What it does

For rolling windows it optimizes parameters on a **train** slice, then scores those
parameters on the **next, unseen test** slice. It stitches all the test (out-of-sample)
trades together and judges *those* — that's the closest proxy to live performance.

## Reading the verdict

- **EDGE HOLDS OUT-OF-SAMPLE** — profit factor > ~1.3 and positive expectancy that holds
  across most windows. Promising → go to weeks of paper trading next.
- **MARGINAL** — weak positive OOS edge. Fragile; needs more data/refinement.
- **OVERFIT** — great in-sample, poor out-of-sample. The "edge" was curve-fitting. Don't trade.
- **NO EDGE** — OOS expectancy not positive after fees. Revise or replace the strategy.
- **INSUFFICIENT DATA** — fewer than ~30 OOS trades. Download more history / lower timeframe.

Also read the **per-window** line (train PF → OOS PF: a big drop = overfitting) and the
**regime / exit-reason breakdown** (e.g. "loses in `range`, wins in `trend_up`", or "stops
average -0.9R" → maybe stops are too tight). Those point to the next change to try.

## The discipline (so "improvement" is real)

1. Change ONE thing (a parameter or rule).
2. Re-run `validate.py`. Keep the change only if **out-of-sample** improves — never judge on
   in-sample.
3. If it passes, paper-trade for weeks and confirm it matches.
4. Commit the change in git with a note in `HANDOFF.md` §3 so you can roll back.

Keep the parameter grid SMALL (it is, on purpose). More knobs = easier to overfit. And
remember: passing validation is **necessary, not sufficient** — live fills differ, and
nothing here guarantees profit. Capital protection first.
