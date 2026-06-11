"""Test setup: redirect the results journal to a temp dir so running the test
suite never writes into the real data/ folder."""
import os
import tempfile

os.environ.setdefault("TRADING_BOT_DATA_DIR",
                      tempfile.mkdtemp(prefix="tradingbot_test_"))
