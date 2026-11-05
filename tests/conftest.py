"""Shared pytest fixtures for the GoldBot test suite."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make the src layout importable regardless of installation mode.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("GOLDBOT_START_LOOP", "0")

from goldbot.core.config import GoldBotSettings  # noqa: E402
from goldbot.core.models import Candle, InstrumentMetadata  # noqa: E402
from goldbot.engine import TradingEngine  # noqa: E402
from goldbot.execution.paper_broker import PaperBroker  # noqa: E402
from goldbot.risk.limits import KillSwitch, RiskLimits  # noqa: E402


def make_candle(
    ts_index: int,
    open_: float = 1950.0,
    high: float = 1955.0,
    low: float = 1948.0,
    close: float = 1952.0,
    symbol: str = "XAUUSD",
    timeframe: str = "15m",
    complete: bool = True,
    volume: float = 100.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp_utc=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        + timedelta(minutes=15 * ts_index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="test",
        is_complete=complete,
    )


@pytest.fixture()
def settings() -> GoldBotSettings:
    """Paper-mode settings pointing at a clean persistence location."""
    return GoldBotSettings(
        mode="paper",
        instrument_symbol="XAUUSD",
        instrument_venue="paper",
        asset_type="spot",
        metadata_verified=False,
        risk_per_trade_pct=0.25,
        max_open_positions=1,
        max_entries_per_day=3,
        max_consecutive_losses=3,
        initial_equity=10_000.0,
    )


@pytest.fixture()
def broker(tmp_path) -> PaperBroker:
    """PaperBroker isolated from the real logs directory."""
    from goldbot.execution.paper_broker import PaperBroker

    return PaperBroker(
        symbol="XAUUSD",
        spread=0.1,
        commission=0.0,
        slippage=0.2,
        partial_fill_probability=0.0,
        timeout_seconds=5,
        initial_equity=10_000.0,
        persistence_path=tmp_path / "orders.json",
        contract_size=100.0,
        current_price=1950.0,
    )


@pytest.fixture()
def instrument() -> InstrumentMetadata:
    return InstrumentMetadata(
        symbol="XAUUSD",
        venue="test",
        asset_type="spot",
        contract_size=100.0,
        tick_size=0.1,
        tick_value=1.0,
        volume_step=0.01,
        min_volume=0.01,
        max_volume=100.0,
        verified=True,
        source="test",
    )


@pytest.fixture()
def risk_limits(settings) -> RiskLimits:
    return RiskLimits(
        risk_per_trade_pct=settings.risk_per_trade_pct,
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        weekly_drawdown_limit_pct=settings.weekly_drawdown_limit_pct,
        max_open_positions=settings.max_open_positions,
        max_entries_per_day=settings.max_entries_per_day,
        max_consecutive_losses=settings.max_consecutive_losses,
    )


@pytest.fixture()
def kill_switch() -> KillSwitch:
    return KillSwitch()


@pytest.fixture()
def engine(settings, tmp_path) -> TradingEngine:
    """TradingEngine over the bundled sample data with isolated state."""
    return TradingEngine(
        settings,
        persistence_path=tmp_path / "engine_orders.json",
    )


__all__ = ["make_candle"]
