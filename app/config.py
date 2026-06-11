"""Central configuration. All values come from environment variables / .env.

Using pydantic-settings means every setting is typed and validated at startup,
and secrets are never hard-coded. Nothing here is ever logged.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- mode ---
    mode: str = Field(default="paper")  # "paper" | "live"

    # --- infra ---
    database_url: str = "postgresql+psycopg2://trader:trader@localhost:5432/trading_bot"
    redis_url: str = "redis://localhost:6379/0"

    # --- exchange (secrets) ---
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True
    bybit_category: str = "linear"

    # --- risk ---
    risk_per_trade: float = 0.005
    daily_max_loss: float = 0.02
    weekly_max_loss: float = 0.05
    max_open_positions: int = 3
    max_leverage: float = 3.0
    max_consecutive_losses: int = 4
    circuit_breaker_atr_mult: float = 4.0

    # --- trading ---
    symbols: str = "BTCUSDT,ETHUSDT"
    base_timeframe: int = 60  # minutes
    min_ai_score: int = 55

    # --- fees / slippage assumptions for paper + backtest ---
    taker_fee_bps: float = 5.5   # Bybit perp taker ~0.055%
    slippage_bps: float = 2.0    # assumed slippage per fill
    spread_bps: float = 1.0      # half-spread cost

    # --- alerts ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def is_live(self) -> bool:
        return self.mode.lower() == "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()
