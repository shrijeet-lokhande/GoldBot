"""Live risk safeguard tests: server-side limits are pure and enforceable."""

from datetime import datetime, timezone

import pytest

from goldbot.risk.safeguards import (
    DuplicateOrderGuard,
    LiveRiskConfig,
    LiveRiskGuard,
)


@pytest.fixture()
def guard() -> LiveRiskGuard:
    return LiveRiskGuard(LiveRiskConfig())


def _ok_order(**overrides):
    base = dict(
        side="buy",
        volume_lots=0.5,
        entry_price=1950.0,
        stop_loss=1945.0,
        take_profit=1965.0,
        equity=250_000.0,
        open_positions=0,
        spread=0.2,
        data_age_seconds=1.0,
        atr=2.0,
        now_utc=datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return base


def test_valid_order_passes(guard):
    decision = guard.check_order(**_ok_order())
    assert decision.allowed, decision.reasons


def test_missing_stop_loss_rejected(guard):
    decision = guard.check_order(**_ok_order(stop_loss=None))
    assert not decision.allowed
    assert any("stop_loss_required" in r for r in decision.reasons)


def test_order_size_cap(guard):
    decision = guard.check_order(**_ok_order(volume_lots=50.0))
    assert not decision.allowed
    assert any("volume" in r for r in decision.reasons)


def test_risk_per_trade_cap(guard):
    # risk = 5.0 * 10 lots * 100 oz/lot = 5000 -> 2% of 250k > 0.5% cap
    decision = guard.check_order(**_ok_order(volume_lots=10.0))
    assert not decision.allowed
    assert any("risk per trade" in r for r in decision.reasons)


def test_min_risk_reward(guard):
    decision = guard.check_order(
        **_ok_order(
            stop_loss=1945.0,
            take_profit=1948.0,
        )
    )
    assert not decision.allowed
    assert any("risk-reward" in r for r in decision.reasons)


def test_max_open_positions(guard):
    decision = guard.check_order(**_ok_order(open_positions=2))
    assert not decision.allowed
    assert any("open positions" in r for r in decision.reasons)


def test_exposure_leverage_cap(guard):
    decision = guard.check_order(
        **_ok_order(
            volume_lots=1.0,
            current_exposure_lots=100.0,
        )
    )
    assert not decision.allowed
    assert any("exposure" in r for r in decision.reasons)
    # Sanity: the base order alone is well inside the cap
    ok = guard.check_order(**_ok_order())
    assert ok.allowed


def test_stale_data_rejected(guard):
    decision = guard.check_order(**_ok_order(data_age_seconds=120.0))
    assert not decision.allowed
    assert any("stale" in r for r in decision.reasons)


def test_missing_data_freshness_rejected(guard):
    decision = guard.check_order(**_ok_order(data_age_seconds=None))
    assert not decision.allowed
    assert any("freshness" in r for r in decision.reasons)


def test_wide_spread_rejected(guard):
    decision = guard.check_order(**_ok_order(spread=5.0))
    assert not decision.allowed
    assert any("spread" in r for r in decision.reasons)


def test_volatility_guard(guard):
    decision = guard.check_order(**_ok_order(atr=25.0))  # ~1.3% of price
    assert not decision.allowed
    assert any("volatility" in r for r in decision.reasons)


def test_weekend_rejected(guard):
    decision = guard.check_order(
        **_ok_order(
            now_utc=datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc),  # Saturday
        )
    )
    assert not decision.allowed
    assert any("session" in r for r in decision.reasons)


def test_outside_session_hours_rejected(guard):
    decision = guard.check_order(
        **_ok_order(
            now_utc=datetime(2026, 11, 9, 3, 0, tzinfo=timezone.utc),  # 03:00 UTC
        )
    )
    assert not decision.allowed
    assert any("session" in r for r in decision.reasons)


def test_daily_loss_limit(guard):
    ok = guard.check_daily_loss(start_equity=10_000.0, current_equity=9_950.0)
    assert ok.allowed
    breached = guard.check_daily_loss(start_equity=10_000.0, current_equity=9_700.0)
    assert not breached.allowed


def test_multiple_reasons_aggregated(guard):
    decision = guard.check_order(
        **_ok_order(
            stop_loss=None,
            spread=9.9,
            data_age_seconds=None,
        )
    )
    assert len(decision.reasons) >= 3


def test_duplicate_order_guard_blocks_reregistration():
    g = DuplicateOrderGuard()
    assert g.register("c1") is True
    assert g.register("c1") is False


def test_duplicate_order_guard_uncertain_state_blocks_retry():
    g = DuplicateOrderGuard()
    g.register("c1")
    g.mark_uncertain("c1")
    assert g.retry_allowed("c1") is False
    g.reconcile("c1", executed=True)
    assert g.retry_allowed("c1") is True
    g.reconcile("c1", executed=True)
    # once executed, the ID stays known: re-registration still blocked
    assert g.register("c1") is False


def test_config_defaults_are_conservative():
    cfg = LiveRiskConfig()
    assert cfg.require_stop_loss is True
    assert cfg.max_risk_per_trade_pct <= 1.0
    assert cfg.max_daily_loss_pct <= 5.0
    assert cfg.max_leverage <= 30.0
