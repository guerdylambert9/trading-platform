"""Settings, read from environment variables or a .env file.

Safe defaults: paper trading, the in-memory fake broker and synthetic prices. Nothing touches
a real account until you change those settings on purpose, and live trading needs two
explicit flags (TRADING_MODE=live and LIVE_TRADING_CONFIRMED=true).
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_UNIVERSE = "SPY,QQQ,IWM,EFA,EEM,TLT,IEF,GLD,DBC,VNQ"
# Point this at another settings file to run a second account, e.g. TRADER_ENV_FILE=../.env.b
ENV_FILE_VAR = "TRADER_ENV_FILE"
# The demo's made-up trades go to their own file unless DATABASE_URL is set.
DEMO_DATABASE_URL = "sqlite:///./demo.db"


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class BrokerKind(StrEnum):
    FAKE = "fake"
    ALPACA = "alpaca"


class DataSourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    CSV = "csv"
    ALPACA = "alpaca"


class AIMode(StrEnum):
    OFF = "off"
    LOG_ONLY = "log_only"
    VETO = "veto"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Where orders go
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_confirmed: bool = False
    dry_run: bool = False
    broker: BrokerKind = BrokerKind.FAKE
    account_label: str = "A"

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_data_feed: str = "sip"
    alpaca_latest_feed: str = "iex"

    # Data and storage (relative paths resolve from the backend/ folder)
    data_source: DataSourceKind = DataSourceKind.SYNTHETIC
    csv_path: str = "data/closes.csv"
    database_url: str = "sqlite:///./trader.db"  # demo.db when BROKER=fake and this isn't set
    fake_broker_state: str = "data/fake_broker.json"
    reports_dir: str = "reports"
    frontend_dist: str = "../frontend/dist"

    # Strategy
    strategy: str = "trend"
    universe: str = DEFAULT_UNIVERSE
    benchmark: str = "SPY"

    # Risk limits (percentages are 0-100)
    risk_per_trade_pct: float = 1.0
    stop_loss_pct: float = 8.0
    max_position_pct: float = 10.0
    max_open_positions: int = 8
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_orders_per_day: int = 10
    no_trade_after_open_min: int = 15
    no_trade_before_close_min: int = 15
    entry_limit_buffer_pct: float = 0.2
    max_gap_pct: float = 2.0
    auto_approve: bool = False

    # AI research layer (Phase 3)
    ai_mode: AIMode = AIMode.OFF
    ai_researcher: str = "null"
    ai_veto_ratings: str = "underweight,sell"
    ai_max_calls_per_day: int = 5
    ai_cost_per_call_usd: float = 0.0

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # API and scheduler
    api_token: str = ""
    cors_origins: str = "http://localhost:5173"
    enable_scheduler: bool = False
    timezone: str = "America/New_York"

    @model_validator(mode="after")
    def _check_live_safety(self) -> Settings:
        if self.trading_mode == TradingMode.LIVE:
            if not self.live_trading_confirmed:
                raise ValueError(
                    "TRADING_MODE=live also needs LIVE_TRADING_CONFIRMED=true. Pass every gate first."
                )
            if self.broker != BrokerKind.ALPACA:
                raise ValueError("TRADING_MODE=live requires BROKER=alpaca.")
        return self

    @model_validator(mode="after")
    def _separate_demo_ledger(self) -> Settings:
        if self.broker == BrokerKind.FAKE and "database_url" not in self.model_fields_set:
            self.database_url = DEMO_DATABASE_URL
        return self

    @property
    def universe_list(self) -> list[str]:
        return [symbol.upper() for symbol in split_csv(self.universe)]

    @property
    def benchmark_symbol(self) -> str:
        return self.benchmark.strip().upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return split_csv(self.cors_origins)

    @property
    def ai_veto_rating_set(self) -> set[str]:
        return {rating.lower() for rating in split_csv(self.ai_veto_ratings)}

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    @property
    def client_order_prefix(self) -> str:
        return f"tp{self.account_label}"

    @property
    def mode_label(self) -> str:
        if self.broker == BrokerKind.FAKE:
            return "DEMO"
        return "LIVE" if self.is_live else "PAPER"


@lru_cache
def get_settings() -> Settings:
    env_file = os.environ.get(ENV_FILE_VAR)
    if env_file:
        if not Path(env_file).is_file():
            raise FileNotFoundError(f"{ENV_FILE_VAR} points to {env_file}, which does not exist.")
        return Settings(_env_file=env_file)
    return Settings()
