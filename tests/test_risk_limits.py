"""RiskLimits and KillSwitch tests."""

import pytest

from goldbot.risk.limits import KillSwitch, RiskLimits


@pytest.fixture()
def limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade_pct=0.25,
        daily_loss_limit_pct=1.0,
        weekly_drawdown_limit_pct=3.0,
        max_open_positions=1,
        max_entries_per_day=3,
        max_consecutive_losses=3,
    )


def test_daily_loss_limit_triggers_on_loss_only(limits):
    limits.set_start_of_day_equity(10_000.0)
    # Gains never trigger the daily limit
    assert limits.check_daily_loss_limit(current_equity=10_500.0)
    # Within limit
    assert limits.check_daily_loss_limit(current_equity=9_950.0)
    # 1% loss exactly -> breach
    assert not limits.check_daily_loss_limit(current_equity=9_900.0)
    # without a daily baseline configured, no breach possible
    fresh = RiskLimits(0.25, 1.0, 3.0, 1, 3, 3)
    assert fresh.check_daily_loss_limit(current_equity=0.0)


def test_weekly_drawdown_limit(limits):
    limits.set_weekly_equity_high(10_000.0)
    assert limits.check_weekly_drawdown_limit(current_equity=9_800.0)
    assert not limits.check_weekly_drawdown_limit(current_equity=9_700.0)
    # gains never trigger the weekly drawdown
    assert limits.check_weekly_drawdown_limit(current_equity=11_000.0)


def test_max_open_positions(limits):
    assert limits.check_max_open_positions(current_positions=0)
    assert limits.check_max_open_positions(current_positions=0)
    assert not limits.check_max_open_positions(current_positions=1)


def test_entries_per_day(limits):
    assert limits.check_max_entries_per_day()
    limits.increment_entries_today()
    limits.increment_entries_today()
    limits.increment_entries_today()
    assert not limits.check_max_entries_per_day()


def test_consecutive_losses_counter(limits):
    limits.record_trade_result(-50.0)
    limits.record_trade_result(-60.0)
    assert limits.consecutive_losses == 2
    assert limits.check_max_consecutive_losses()
    limits.record_trade_result(-10.0)
    assert limits.consecutive_losses == 3
    assert not limits.check_max_consecutive_losses()
    # a win resets the counter
    limits.record_trade_result(40.0)
    assert limits.consecutive_losses == 0
    assert limits.check_max_consecutive_losses()


def test_daily_reset_clears_counters(limits):
    limits.set_start_of_day_equity(10_000.0)
    for _ in range(3):
        limits.increment_entries_today()
    limits.record_trade_result(-10.0)
    limits.record_trade_result(-10.0)
    limits.record_trade_result(-10.0)
    assert not limits.check_max_entries_per_day()
    assert not limits.check_max_consecutive_losses()
    # A new simulated day resets both
    limits.reset_daily_counter()
    limits.set_start_of_day_equity(9_900.0)
    assert limits.check_max_entries_per_day()
    assert limits.check_max_consecutive_losses()


def test_kill_switch_manual_activation():
    ks = KillSwitch()
    assert not ks.active
    ks.activate("manual test")
    assert ks.active
    assert ks.reasons == ["manual test"]
    ks.deactivate()
    assert not ks.active
    assert ks.reasons == []


def test_kill_switch_condition_matrix(limits):
    limits.set_start_of_day_equity(10_000.0)
    ks = KillSwitch(max_spread=0.5, max_slippage=1.0)
    # Healthy state: trading allowed
    assert not ks.check_and_block(
        risk_limits=limits,
        instrument_metadata=_instrument(True),
        current_equity=10_000.0,
    )
    # Spread breach blocks
    assert ks.check_and_block(
        risk_limits=limits,
        instrument_metadata=_instrument(True),
        spread=1.0,
    )
    ks.deactivate()
    # Stale data blocks
    assert ks.check_and_block(
        risk_limits=limits, instrument_metadata=_instrument(True), stale_data=True
    )
    ks.deactivate()
    # Unverified metadata blocks
    assert ks.check_and_block(risk_limits=limits, instrument_metadata=_instrument(False))
    ks.deactivate()
    # Daily-limit breach blocks
    assert ks.check_and_block(
        risk_limits=limits, instrument_metadata=_instrument(True), current_equity=9_000.0
    )


def _instrument(verified: bool):
    from goldbot.core.models import InstrumentMetadata

    return InstrumentMetadata(symbol="XAUUSD", verified=verified)
