"""GoldBot configuration loading, validation, and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoldBotSettings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="GOLD_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # App identity
    app_name: str = Field(default="goldbot")
    environment: str = Field(default="development")
    timezone_storage: str = Field(default="UTC")

    # Mode: paper or live
    mode: str = Field(default="paper")

    # Instrument
    instrument_symbol: Optional[str] = None
    instrument_venue: Optional[str] = None
    asset_type: Optional[str] = None
    metadata_verified: bool = False

    # Market data
    market_data_provider: str = Field(default="csv")
    entry_timeframe: str = Field(default="15m")
    trend_timeframe: str = Field(default="1h")
    history_lookback_days: int = Field(default=730)
    stale_data_seconds: int = Field(default=120)
    require_bid_ask: bool = True

    # Strategy
    strategy_name: str = Field(default="trend_pullback")
    ema_fast: int = 20
    ema_trend: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    rsi_threshold: float = 40.0
    atr_period: int = 14
    adx_period: int = 14
    minimum_adx: float = 20.0
    candle_close_only: bool = True

    # Risk
    risk_per_trade_pct: float = 0.25
    daily_loss_limit_pct: float = 1.0
    weekly_drawdown_limit_pct: float = 3.0
    max_open_positions: int = 1
    max_entries_per_day: int = 3
    max_consecutive_losses: int = 3
    max_spread: Optional[float] = None
    max_slippage: Optional[float] = None
    allow_martingale: bool = False
    allow_grid: bool = False
    allow_averaging_down: bool = False

    # Execution
    adapter: str = Field(default="paper")
    allow_live_orders: bool = False
    allow_short: bool = True
    require_stop_loss: bool = True
    reject_duplicate_signal: bool = True
    order_timeout_seconds: int = 10

    # Storage
    database_url: Optional[str] = None
    store_raw_market_data: bool = True

    # Replay / simulation
    initial_equity: float = 10_000.0
    replay_speed: float = 1.0  # multiplier on the replay step interval

    # Monitoring
    telegram_enabled: bool = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        if v not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        return v

    @field_validator("risk_per_trade_pct", "daily_loss_limit_pct", "weekly_drawdown_limit_pct")
    @classmethod
    def risk_percentages_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("risk percentages must be positive")
        return v

    @field_validator("max_open_positions", "max_entries_per_day", "max_consecutive_losses")
    @classmethod
    def counts_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("count limits must be >= 1")
        return v

    @field_validator("initial_equity")
    @classmethod
    def initial_equity_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("initial_equity must be positive")
        return v

    @model_validator(mode="after")
    def live_mode_guards(self) -> "GoldBotSettings":
        """Safety gates required before live mode is accepted."""
        if self.mode == "live":
            missing = [
                name
                for name, val in (
                    ("instrument_symbol", self.instrument_symbol),
                    ("instrument_venue", self.instrument_venue),
                    ("asset_type", self.asset_type),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"fields required when mode is 'live': {missing}")
            if not self.metadata_verified:
                raise ValueError("metadata_verified must be true when mode is 'live'")
            # v1 ships the paper broker only: live orders are impossible.
            self.allow_live_orders = False
            self.allow_martingale = False
            self.allow_grid = False
            self.allow_averaging_down = False
        return self

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "GoldBotSettings":
        """Load settings from a YAML file over the defaults."""
        from yaml import safe_load

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        data = safe_load(path.read_text()) or {}
        return cls(**data)


def load_settings(
    config_path: str | Path = "config/settings.yaml",
    override_env: bool = True,
) -> GoldBotSettings:
    """Load and validate GoldBot settings.

    Priority: environment variables > YAML config > defaults.

    Raises:
        FileNotFoundError: when ``config_path`` is explicitly provided and
            does not exist.
    """
    from yaml import safe_load

    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    data = safe_load(config_path.read_text()) or {}
    settings = GoldBotSettings(**data)

    # Environment variables (GOLD_<FIELD>) beat YAML values. Use a live
    # environment field lookup so tests can set env vars per run.
    for field_name in type(settings).model_fields:
        env_key = f"GOLD_{field_name.upper()}"
        if env_key in os.environ:
            raw = os.environ[env_key]
            yield_type = type(getattr(settings, field_name))
            value: object
            try:
                if yield_type is bool:
                    value = raw.lower() in ("1", "true", "yes", "on")
                elif yield_type in (int, float):
                    value = yield_type(raw)
                else:
                    value = raw
                setattr(settings, field_name, value)
            except (ValueError, TypeError):
                logger_name = __name__
                import logging

                logging.getLogger(logger_name).warning(
                    "Ignoring non-conforming env override %s=%s", env_key, raw
                )
    # Re-validate after overrides
    return GoldBotSettings.model_validate(settings.model_dump())
