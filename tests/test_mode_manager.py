"""Trading mode manager tests: safety gates, audit, no-silent-switch rules."""

import pytest

from goldbot.execution.mode_manager import (
    CONFIRMATION_PHRASE,
    TradingModeManager,
)


@pytest.fixture()
def manager() -> TradingModeManager:
    return TradingModeManager()


def test_defaults_to_paper(manager):
    assert manager.mode == "paper"


def test_switch_to_live_denied_without_broker(manager):
    result = manager.switch_mode("live")
    assert result["status"] == "denied"
    assert manager.mode == "paper"


def test_switch_to_live_denied_without_authorization(manager):
    manager.set_broker_connection(True, detail="test")
    result = manager.switch_mode("live")
    assert result["status"] == "denied"
    assert manager.mode == "paper"


def test_live_switch_requires_exact_confirmation(manager):
    manager.set_broker_connection(True, detail="test")
    result = manager.authorize_live("enable live trading")  # wrong case
    assert result["authorized"] is False
    result = manager.authorize_live(CONFIRMATION_PHRASE)
    assert result["authorized"] is True
    switch = manager.switch_mode("live")
    assert switch["status"] == "ok"
    assert manager.mode == "live"


def test_invalid_mode_denied(manager):
    assert manager.switch_mode("yolo")["status"] == "denied"


def test_switch_to_same_mode_is_noop(manager):
    result = manager.switch_mode("paper")
    assert result["status"] == "already"
    assert manager.mode == "paper"


def test_switch_back_to_paper_revokes_authorization(manager):
    manager.set_broker_connection(True, detail="test")
    manager.authorize_live(CONFIRMATION_PHRASE)
    manager.switch_mode("live")
    result = manager.switch_mode("paper")
    assert result["status"] == "ok"
    assert manager.live_authorized is False


def test_broker_disconnect_forces_paper(manager):
    manager.set_broker_connection(True, detail="test")
    manager.authorize_live(CONFIRMATION_PHRASE)
    manager.switch_mode("live")
    manager.set_broker_connection(False, detail="connection lost")
    assert manager.mode == "paper"
    assert manager.live_authorized is False


def test_transition_plan_never_transfers_positions(manager):
    plan = manager.plan_transition("live").to_dict()
    assert "remain" in plan["open_positions_kept_in_original_mode"][0]
    assert "explicitly" in plan["pending_orders_cancelled_in_original_mode"][0]
    # A live switch must not silently close anything
    assert "close" not in plan["note"].lower() or "not" in plan["note"].lower()


def test_audit_trail_records_denied_attempts(manager):
    manager.switch_mode("live")  # denied
    manager.authorize_live("wrong phrase")
    events = [e.to_dict() for e in manager.audit_trail]
    names = [e["event"] for e in events]
    assert "mode_switch_denied" in names
    assert "live_authorization_denied" in names
    assert all("token" not in str(e).lower() for e in events)


def test_audit_sink_receives_events():
    received: list = []
    manager = TradingModeManager(audit_sink=received.append)
    manager.switch_mode("live")
    assert len(received) == 1
    assert received[0].event == "mode_switch_denied"
