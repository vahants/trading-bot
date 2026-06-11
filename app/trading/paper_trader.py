"""Paper trading entrypoint (kept for convenience / docker `worker`).

Thin wrapper over app.trading.runner. With MODE=paper in .env this runs simulated
fills on real Bybit data; the same runner handles live when MODE=live.

Run:  python -m app.trading.paper_trader     (or simply: python run.py)
"""
from __future__ import annotations

import logging

from app.trading.runner import build_engine, run_loop  # re-exported

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main(poll_seconds: int = 60):
    run_loop(poll_seconds=poll_seconds)


if __name__ == "__main__":
    main()
