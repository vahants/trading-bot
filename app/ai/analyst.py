"""AI layer — ADVISORY ONLY. It can never create or enlarge a trade.

Authority boundary (see ARCHITECTURE.md §10): the AI may summarize, score (0-100),
explain, and flag risk. The engine uses the score solely as an extra *filter*:
trades scoring below ``MIN_AI_SCORE`` are skipped. It can lower conviction, never
raise it. The rule-based strategy + RiskManager remain the only source of trades.

This MVP ships a transparent heuristic scorer (no external API, fully testable).
Swap ``assess`` for an LLM call later — the interface stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.strategies.base import Signal


@dataclass
class AIAssessment:
    score: int            # 0-100 trade quality
    summary: str
    risks: list[str]
    allow: bool           # score >= threshold


class AIAnalyst:
    def __init__(self, min_score: int = 55):
        self.min_score = min_score

    def assess(self, signal: Signal, df: pd.DataFrame) -> AIAssessment:
        last = df.iloc[-1]
        score = 50
        risks: list[str] = []

        # Reward trend alignment and momentum room.
        if "ema_fast" in df.columns and "ema_slow" in df.columns:
            trend_up = last["ema_fast"] > last["ema_slow"]
            aligned = (signal.side.value == "long" and trend_up) or \
                      (signal.side.value == "short" and not trend_up)
            score += 15 if aligned else -20
            if not aligned:
                risks.append("signal against higher-level trend")

        rsi = last.get("rsi", 50)
        if 40 <= rsi <= 60:
            score += 10  # room to move, not exhausted
        elif rsi > 75 or rsi < 25:
            score -= 10
            risks.append(f"RSI extended ({rsi:.0f})")

        # Volume confirmation.
        if "vol_ma" in df.columns and last.get("vol_ma"):
            if last["volume"] > last["vol_ma"]:
                score += 10
            else:
                risks.append("below-average volume")

        # Reward a healthy reward:risk.
        if signal.take_profit:
            rr = abs(signal.take_profit - signal.entry) / max(signal.risk_per_unit, 1e-9)
            if rr >= 1.5:
                score += 10
            elif rr < 1.0:
                score -= 10
                risks.append(f"poor reward:risk ({rr:.2f})")

        score = max(0, min(100, score))
        summary = (f"{signal.side.value} {signal.reason}; "
                   f"RSI {rsi:.0f}; score {score}/100")
        return AIAssessment(score=score, summary=summary, risks=risks,
                            allow=score >= self.min_score)
