"""Telegram notifier — optional. No token configured => silent no-op.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to receive alerts for every
open/close, halt, circuit-breaker and kill-switch event. Uses the HTTP Bot API;
failures are swallowed so alerting can never take the bot down.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger("telegram")


class TelegramNotifier:
    def __init__(self, settings=None):
        cfg = settings or get_settings()
        self.token = cfg.telegram_bot_token
        self.chat_id = cfg.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            log.info("Telegram alerts disabled (no token/chat id).")

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            httpx.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=5)
        except Exception as e:  # never let alerting break trading
            log.warning("Telegram send failed: %s", e)
