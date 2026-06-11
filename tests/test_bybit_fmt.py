"""Unit tests for Bybit value formatting (precision/step rounding).

These guard against the live-order rejections Bybit throws when qty/price don't
match the symbol's step/tick. No network or pybit needed — _fmt is pure.
"""
from app.exchanges.bybit import BybitExchange


def test_qty_floored_to_step():
    # never size ABOVE what risk approved -> floor
    assert BybitExchange._fmt(0.62100001, 0.001, floor=True) == "0.621"
    assert BybitExchange._fmt(0.6219, 0.001, floor=True) == "0.621"
    assert BybitExchange._fmt(0.0009, 0.001, floor=True) == "0"   # below 1 step


def test_price_rounded_to_tick():
    assert BybitExchange._fmt(62758.74, 0.1) == "62758.7"
    assert BybitExchange._fmt(100.0, 0.5) == "100"
    assert BybitExchange._fmt(100.26, 0.05) == "100.25"


def test_no_float_artifacts():
    # 0.1+0.2 style artifacts must not leak into the order string
    out = BybitExchange._fmt(0.3, 0.1)
    assert out == "0.3" and "0000" not in out
