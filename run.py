"""Single entrypoint to start the bot.

  python run.py

It reads MODE from .env:
  * paper  -> simulated fills on REAL Bybit data. No API key needed.
  * live   -> real orders. Requires BYBIT_API_KEY / BYBIT_API_SECRET.
              Starts on testnet while BYBIT_TESTNET=true.

A preflight check validates configuration and connectivity before any trading,
and prints exactly what (if anything) you still need to set.
"""
from __future__ import annotations

import logging
import sys

from app.config import get_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("run")


def preflight(cfg) -> bool:
    print("=" * 60)
    print(f"  MODE:      {cfg.mode.upper()}")
    print(f"  Exchange:  Bybit ({'testnet' if cfg.bybit_testnet else 'MAINNET'})")
    print(f"  Symbols:   {', '.join(cfg.symbol_list)}")
    print(f"  Risk/trade:{cfg.risk_per_trade:.2%}  Daily cap:{cfg.daily_max_loss:.1%}"
          f"  Max lev:{cfg.max_leverage}x")
    print("=" * 60)

    if cfg.is_live:
        if not (cfg.bybit_api_key and cfg.bybit_api_secret):
            print("\n[X] LIVE mode needs API keys. Edit .env and set:")
            print("      BYBIT_API_KEY=...")
            print("      BYBIT_API_SECRET=...")
            print("    Create a key on Bybit with: trade ON, withdrawals OFF,")
            print("    IP allow-list ON. Keep BYBIT_TESTNET=true to start safely.")
            return False
        if not cfg.bybit_testnet:
            print("\n[!] You are about to trade REAL money on Bybit MAINNET.")
            if input("    Type 'I UNDERSTAND' to continue: ").strip() != "I UNDERSTAND":
                print("    Aborted.")
                return False

    # connectivity check (public data — also validates pybit is installed)
    try:
        from app.exchanges.bybit import BybitExchange
        px = BybitExchange().get_last_price(cfg.symbol_list[0])
        print(f"[ok] Connected. {cfg.symbol_list[0]} last price: {px}")
    except Exception as e:
        print(f"\n[X] Could not reach Bybit / load pybit: {e}")
        print("    Run: pip install -r requirements.txt")
        return False

    if cfg.is_live and cfg.bybit_api_key:
        try:
            bal = BybitExchange().get_balance()
            print(f"[ok] Account equity: {bal.equity}")
        except Exception as e:
            print(f"\n[X] API keys rejected by Bybit: {e}")
            return False

    return True


def main():
    cfg = get_settings()
    if not preflight(cfg):
        sys.exit(1)
    print(f"\nStarting {cfg.mode.upper()} loop. Ctrl+C to stop.\n")
    from app.trading.runner import run_loop
    try:
        run_loop(poll_seconds=60)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
