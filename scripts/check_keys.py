"""Pre-flight: confirm your Bybit key works BEFORE running the trading loop.

Read-only — it does NOT place any orders. It:
  1. checks your keys are filled in,
  2. connects and authenticates (proves the key is valid + has access),
  3. prints your account equity,
  4. for each configured symbol, shows price + the minimum order you can place,
     and whether your equity is enough for the bot's risk-sized orders.

Run:  python scripts/check_keys.py
"""
from __future__ import annotations

import os
import sys

# Make the project root importable when run as `python scripts/check_keys.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings


def main():
    cfg = get_settings()
    print("=" * 58)
    print(f"  MODE={cfg.mode}  TESTNET={cfg.bybit_testnet}  category={cfg.bybit_category}")
    print("=" * 58)

    if cfg.mode == "paper":
        print("MODE=paper -> no key needed. Just run:  python run.py")
        return

    placeholders = ("", "PASTE_YOUR_TESTNET_KEY_HERE", "PASTE_YOUR_TESTNET_SECRET_HERE")
    if cfg.bybit_api_key in placeholders or cfg.bybit_api_secret in placeholders:
        print("[X] Keys not set. Edit .env and paste your TESTNET key + secret:")
        print("      BYBIT_API_KEY=...")
        print("      BYBIT_API_SECRET=...")
        print("    Get them at https://testnet.bybit.com -> API Management.")
        sys.exit(1)

    try:
        from app.exchanges.bybit import BybitExchange
    except Exception as e:
        print(f"[X] pybit not installed: {e}\n    Run: pip install -r requirements.txt")
        sys.exit(1)

    ex = BybitExchange()

    # 1) auth + balance
    try:
        bal = ex.get_balance()
    except ModuleNotFoundError as e:
        print(f"[X] Missing dependency: {e}\n    Run: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"[X] Key rejected / connection failed: {e}")
        print("    Check: key is a TESTNET key, Trade permission ON, IP allow-list,")
        print("           and your IP is whitelisted.")
        sys.exit(1)
    print(f"[ok] Authenticated. Account equity: {bal.equity} USDT "
          f"(available {bal.available})")
    if bal.equity <= 0:
        print("[!] Equity is 0 — fund the TESTNET wallet from the faucet in the")
        print("    testnet UI (Assets), then re-run this check.")

    # 2) per-symbol sizing sanity
    print("\nSymbol checks:")
    for sym in cfg.symbol_list:
        try:
            info = ex.get_symbol_info(sym)
            px = ex.get_last_price(sym)
        except Exception as e:
            print(f"  {sym}: [X] could not load ({e})")
            continue
        min_qty_notional = max(info.qty_step, info.min_notional / px) * px
        # bot sizes ~ equity * risk / stop_pct ; assume ~3% stop as a rough guide
        approx_notional = bal.equity * cfg.risk_per_trade / 0.03
        ok = approx_notional >= min_qty_notional
        print(f"  {sym}: price {px} | min order ~{min_qty_notional:.2f} USDT | "
              f"bot order ~{approx_notional:.2f} USDT -> "
              f"{'OK' if ok else 'TOO SMALL (add funds or use a cheaper symbol)'}")

    print("\nAll good? Start the bot:  python run.py")


if __name__ == "__main__":
    main()
