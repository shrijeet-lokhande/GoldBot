"""RiskEngine decision-matrix tests."""

import pytest

from goldbot.core.models import InstrumentMetadata, Signal
from goldbot.risk.engine import RiskEngine
from goldbot.risk.limits import KillSwitch, RiskLimits


@pytest.fixture()
def instrument():
    return InstrumentMetadata(
        symbol="XAUUSD", venue="test", asset_type="spot",
        contract_size=100.0, tick_size=0.1, tick_value=1.0,
        volume_step=0.01, min_volume=0.01, max_volume=100.0,
        verified=True, source="test",
    )


def make_signal(direction="long", stop_distance=20.0):
    from datetime import datetime, timezone

    return Signal(
        symbol="XAUUSD",
        direction=direction,
        created_at_utc=datetime.now(timezone.utc),
        reference_price=2000.0,
        stop_distance=stop_distance,
        take_profit_multiple=2.0,
        timeframe="15m",
    )


@pytest.fixture()
def engine(instrument):
    limits = RiskLimits(
        risk_per_trade_pct=0.25, daily_loss_limit_pct=1.0,
        weekly_drawdown_limit_pct=3.0, max_open_positions=1,
        max_entries_per_day=3, max_consecutive_losses=3,
    )
    limits.set_start_of_day_equity(10_000.0)
    limits.set_weekly_equity_high(10_000.0)
    return RiskEngine(
        risk_limits=limits, kill_switch=KillSwitch(),
        instrument_metadata=instrument, equity=10_000.0,
    )


def test_approval_happy_path(engine):
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=10_000.0,
    )
    assert decision["decision"] == "approve"
    assert decision["position_size"] == pytest.approx(0.01)
    assert not decision["kill_switched"]


def test_kill_switch_blocks(engine):
    engine.kill_switch.activate("test")
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=10_000.0,
    )
    assert decision["decision"] == "reject"
    assert decision["kill_switched"]


def test_unverified_metadata_rejects(engine):
    engine.instrument_metadata.verified = False
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=10_000.0,
    )
    assert decision["decision"] == "reject"
    assert "verified" in decision["reason"]


def test_daily_loss_limit_blocks(engine):
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=9_850.0,  # > 1% loss from 10k baseline
    )
    assert decision["decision"] == "reject"
    assert "daily loss" in decision["reason"]


def test_weekly_drawdown_blocks():
    """Weekly check isolated from the tighter daily limit."""

    limits = RiskLimits(
        risk_per_trade_pct=0.25, daily_loss_limit_pct=10.0,
        weekly_drawdown_limit_pct=3.0, max_open_positions=1,
        max_entries_per_day=3, max_consecutive_losses=3,
    )
    limits.set_start_of_day_equity(10_000.0)
    limits.set_weekly_equity_high(10_000.0)
    engine = RiskEngine(
        risk_limits=limits, kill_switch=KillSwitch(),
        instrument_metadata=InstrumentMetadata(
            symbol="XAUUSD", contract_size=100.0, tick_size=0.1,
            tick_value=1.0, volume_step=0.01, min_volume=0.01,
            max_volume=100.0, verified=True, source="test",
        ),
        equity=10_000.0,
    )
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=9_650.0,  # 3.5% below the 10k weekly high
    )
    assert decision["decision"] == "reject"
    assert "weekly drawdown" in decision["reason"]


def test_max_open_positions_blocks(engine):
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_positions=1, current_equity=10_000.0,
    )
    assert decision["decision"] == "reject"
    assert "open positions" in decision["reason"]


def test_entries_per_day_blocks(engine):
    for _ in range(3):
        engine.risk_limits.increment_entries_today()
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=10_000.0,
    )
    assert decision["decision"] == "reject"
    assert "entries per day" in decision["reason"]


def test_consecutive_losses_block(engine):
    for _ in range(3):
        engine.risk_limits.record_trade_result(-100.0)
    decision = engine.evaluate_signal(
        signal=make_signal(), entry_price=2000.0, stop_price=1980.0,
        current_equity=10_000.0,
    )
    assert decision["decision"] == "reject"
    assert "consecutive" in decision["reason"]


def test_sizing_scales_with_live_equity(engine):
    big = engine.evaluate_signal(
        signal=make_signal(stop_distance=25.0),
        entry_price=2000.0, stop_price=1975.0,
        current_equity=200_000.0,  # $500 budget -> 0.20 lots
    )
    assert big["decision"] == "approve"
    assert big["position_size"] == pytest.approx(0.20)
