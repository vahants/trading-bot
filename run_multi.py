"""Entrypoint: run ALL strategies in parallel (paper shootout).

  python run_multi.py

Each strategy trades its own simulated account on the same real prices. Compare
them any time with:  python scripts/report.py --compare
"""
from __future__ import annotations

import logging

from app.config import get_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main():
    cfg = get_settings()
    print("=" * 60)
    print("  MULTI-STRATEGY PAPER SHOOTOUT")
    print(f"  Symbols: {', '.join(cfg.symbol_list)}   "
          f"Risk/trade: {cfg.risk_per_trade:.2%}")
    print("  Each strategy runs its own $10k simulated account.")
    print("  Compare any time:  python scripts/report.py --compare")
    print("=" * 60)
    if cfg.is_live:
        print("MODE=live not allowed here. Set MODE=paper in .env.")
        return
    from app.trading.multi_runner import run_multi
    try:
        run_multi(poll_seconds=60)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
