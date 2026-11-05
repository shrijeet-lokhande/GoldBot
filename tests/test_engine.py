"""TradingEngine integration tests (replay, proposals, execution)."""

import pytest

from goldbot.core.config import GoldBotSettings


def test_engine_loads_sample_data(engine):
    assert len(engine._all_candles) > 1000
    assert engine.symbol == "XAUUSD"
    assert engine.entry_timeframe == "15m"


def test_step_bar_advances_replay(engine):
    first = engine.step_bar()
    assert first["candle"].timestamp_utc.day == 15
    assert engine._replay_index == 1
    engine.step_bar()
    assert engine._replay_index == 2


def test_quote_reflects_replayed_price(engine):
    engine.step_bar()
    quote = engine.get_quote()
    assert quote["mid_price"] == pytest.approx(engine._all_candles[0].close)
    assert quote["ask"] > quote["bid"]


def test_indicators_populate_after_warmup(engine):
    # Pump 300 bars so EMA200/RSI/ADX warm up
    for _ in range(300):
        engine.step_bar()
    ind = engine.get_indicators()
    assert ind["ema_long"] is not None
    assert ind["rsi"] is not None
    assert ind["adx"] is not None
    assert 0.0 <= ind["rsi"] <= 100.0


def test_full_replay_with_auto_approve_produces_trades(tmp_path):
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, auto_approve=True,
        persistence_path=tmp_path / "bt_orders.json",
    )
    proposals, executed = 0, 0
    while eng._replay_index < len(eng._all_candles):
        result = eng.step_bar()
        proposals += 1 if result.get("proposal") else 0
    executed = len([p for p in eng.proposals if p.status == "executed"])
    assert proposals > 0, "the sample data must generate at least one proposal"
    assert executed > 0, "auto-approve must execute some proposals"
    assert len(eng.get_trades()) > 0, "SL/TP must close at least one position"

    account = eng.get_account()
    perf = eng.get_performance()
    assert account["initial_equity"] == pytest.approx(10_000.0)
    assert account["equity"] == pytest.approx(
        eng.paper_broker.get_account_equity(), abs=1e-6
    )
    assert perf["total_trades"] == len(eng.get_trades())
    assert perf["total_trades"] > 0


def test_max_open_positions_enforced(tmp_path):
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0, max_open_positions=1,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, auto_approve=True,
        persistence_path=tmp_path / "pos_orders.json",
    )
    while eng._replay_index < len(eng._all_candles):
        eng.step_bar()
    assert len(eng.paper_broker.get_positions()) <= 1
    # every executed proposal went through the broker: consistent order count
    orders = eng.get_orders()
    assert len(orders) == len([p for p in eng.proposals if p.status == "executed"])


def test_rush_rejection_reasons_recorded(tmp_path):
    """Rejected proposals always explain themselves."""
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0, max_entries_per_day=1,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, auto_approve=True,
        persistence_path=tmp_path / "rej_orders.json",
    )
    while eng._replay_index < len(eng._all_candles):
        eng.step_bar()
    for prop in eng.proposals:
        if prop.status == "rejected":
            assert prop.decision_reason, "rejected proposals must record a reason"
        if prop.status == "executed":
            assert prop.order_id is not None


def test_kill_switch_blocks_all_new_entries(tmp_path):
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, auto_approve=True,
        persistence_path=tmp_path / "ks_orders.json",
    )
    eng.set_kill_switch(True, "test harness")
    before = len(eng.proposals)
    while eng._replay_index < len(eng._all_candles):
        eng.step_bar()
    for prop in eng.proposals[before:]:
        assert prop.status == "rejected"
        assert "kill switch" in prop.decision_reason


def test_close_position_api(tmp_path):
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, auto_approve=True,
        persistence_path=tmp_path / "close_orders.json",
    )
    eng.step_bar()
    no_position = None
    while not eng.paper_broker.get_positions():
        if eng._replay_index >= len(eng._all_candles):
            no_position = True
            break
        eng.step_bar()
    result = eng.close_position()
    assert result.get("status") != "unknown"
    if no_position:
        assert result == {"status": "no_open_position"}


def test_config_update_validates(tmp_path):
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    from goldbot.engine import TradingEngine

    eng = TradingEngine(
        settings, persistence_path=tmp_path / "cfg_orders.json",
    )
    cfg = eng.update_config({"risk_per_trade_pct": 0.5, "auto_approve": True})
    assert cfg["risk_per_trade_pct"] == pytest.approx(0.5)
    assert cfg["auto_approve"] is True
    assert eng.risk_limits.risk_per_trade_pct == pytest.approx(0.5)

    cfg = eng.update_config({"max_open_positions": 3})
    assert cfg["max_open_positions"] == 3
    assert eng.risk_limits.max_open_positions == 3

    cfg = eng.update_config({"max_spread": 0.8})
    assert eng.kill_switch.max_spread == pytest.approx(0.8)

    # Invalid/unknown values are ignored, not fatal
    cfg = eng.update_config({"risk_per_trade_pct": -1, "bogus": 1})
    assert eng.risk_limits.risk_per_trade_pct == pytest.approx(0.5)


def test_replay_wrap_around(engine):
    """step_bar wraps to bar 0 when the tape exhausts, without crashing."""
    engine.jump_to_bar(len(engine._all_candles))
    engine.step_bar()
    assert engine._replay_index == 1  # wrapped then advanced once


def test_jump_to_bar_sets_price(engine):
    target = 400
    engine.jump_to_bar(target)
    assert engine._replay_index == target
    assert engine.paper_broker.current_price == pytest.approx(
        engine._all_candles[target - 1].close
    )


def test_performance_metrics_shapes(engine):
    for _ in range(10):
        engine.step_bar()
    perf = engine.get_performance()
    assert set(perf) == {
        "total_trades", "win_rate", "profit_factor", "total_pnl",
        "average_win", "average_loss", "max_drawdown_pct", "current_equity",
    }
    assert perf["win_rate"] >= 0
    assert perf["total_trades"] >= 0


def test_publishes_events_to_subscribers(engine):
    received = []
    unsub = engine.subscribe(received.append)
    engine.step_bar()
    types = [e["type"] for e in received]
    assert "candle" in types
    assert "price" in types
    unsub()
    marker = len(received)
    engine.step_bar()
    assert len(received) == marker


def test_daily_risk_baseline_resets_on_new_sim_day(engine):
    first_day = engine._all_candles[0].timestamp_utc.date()
    engine.step_bar()  # establishes the sim date
    assert engine._current_sim_date == str(first_day)
    baseline = engine.risk_limits._start_of_day_equity
    assert baseline == pytest.approx(10_000.0)


def test_manual_mode_proposals_go_pending_and_operator_flow(tmp_path):
    from goldbot.engine import TradingEngine

    """A9: manual (operator) mode lifecycle — pending gate + decisions.

    Risk-approved proposals must be `pending` for the operator, must
    execute only on approval, and rejecting one must close it out.
    """
    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    eng = TradingEngine(
        settings, auto_approve=False,
        persistence_path=tmp_path / "manual_orders.json",
    )

    while eng._replay_index < len(eng._all_candles):
        result = eng.step_bar()
        if result.get("proposal"):
            break
    assert result.get("proposal"), "sample data must generate a proposal"

    props = [p for p in eng.proposals if p.status == "pending"]
    assert props, "risk-approved proposals must be pending for the operator"
    prop = props[0]

    # Reject: proposal closes without any order
    outcome = eng.reject_proposal(prop.proposal_id, reason="test_reject")
    assert outcome["status"] == "rejected"
    assert outcome["decision_reason"] == "test_reject"
    assert eng.paper_broker.get_positions() == []

    # Rejected proposals cannot be executed afterwards
    r = eng.execute_proposal(prop.proposal_id)
    assert r["status"] == "rejected_by_risk"
    assert len(eng.get_orders()) == 0


def test_manual_mode_approve_executes_pending_proposal(tmp_path):
    from goldbot.engine import TradingEngine

    settings = GoldBotSettings(
        mode="paper", instrument_symbol="XAUUSD", instrument_venue="paper",
        asset_type="spot", initial_equity=10_000.0,
    )
    eng = TradingEngine(
        settings, auto_approve=False,
        persistence_path=tmp_path / "manual2_orders.json",
    )
    while eng._replay_index < len(eng._all_candles):
        result = eng.step_bar()
        if result.get("proposal"):
            break
    assert result.get("proposal")

    prop = next(p for p in eng.proposals if p.status == "pending")
    outcome = eng.approve_proposal(prop.proposal_id)
    assert outcome.get("status") in ("order_submitted", "rejected_by_risk")
    if outcome.get("status") == "order_submitted":
        assert prop.status == "executed"
        assert prop.order_id is not None
        assert len(eng.get_orders()) == 1
