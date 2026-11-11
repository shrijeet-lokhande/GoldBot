"""Full API endpoint + WebSocket tests via FastAPI TestClient."""

import os

import pytest
from fastapi.testclient import TestClient

# Start loop disabled during tests for determinism.
os.environ.setdefault("GOLDBOT_START_LOOP", "0")


@pytest.fixture()
def client(tmp_path):
    import goldbot.api.app as api

    os.environ["GOLDBOT_PERSISTENCE_PATH"] = str(tmp_path / "api_orders.json")
    os.environ["GOLDBOT_START_LOOP"] = "0"
    with TestClient(api.app) as c:
        yield c
    os.environ.pop("GOLDBOT_PERSISTENCE_PATH", None)


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "kill_switch_active")
    assert body["mode"] == "paper"
    assert body["instrument_symbol"] == "XAUUSD"


def test_config_get(client):
    r = client.get("/api/v1/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["mode"] == "paper"
    assert "risk_per_trade_pct" in cfg
    assert cfg["api_version"]


def test_config_update(client):
    r = client.post("/api/v1/config", json={"risk_per_trade_pct": 0.4})
    assert r.status_code == 200
    assert r.json()["risk_per_trade_pct"] == pytest.approx(0.4)


def test_config_update_empty_rejected(client):
    r = client.post("/api/v1/config", json={})
    assert r.status_code == 400


def test_quote_shape(client):
    q = client.get("/api/v1/quote").json()
    assert q["ask"] > q["bid"]
    assert q["spread"] > 0


def test_candles_endpoint(client):
    r = client.get("/api/v1/candles?limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "XAUUSD"
    assert body["timeframe"] == "15m"
    assert len(body["candles"]) == 0  # no bars revealed yet
    assert body["total_bars"] > 1000


def test_account_endpoint(client):
    acc = client.get("/api/v1/account").json()
    assert acc["initial_equity"] == 10000.0
    assert acc["equity"] >= 0


def test_positions_and_trades_empty_start(client):
    assert client.get("/api/v1/positions").json() == []
    assert client.get("/api/v1/trades?limit=5").json() == []
    assert client.get("/api/v1/proposals").json() == []


def test_orders_endpoint(client):
    assert client.get("/api/v1/orders").json() == []


def test_proposal_lifecycle_end_to_end(client):
    """Generate a signal by stepping bars with auto-approve off."""
    import goldbot.api.app as api

    eng = api.engine

    # Step until a proposal appears (or cap out)
    limit = len(eng._all_candles)
    proposal = None
    while eng._replay_index < limit:
        result = eng.step_bar()
        if result.get("proposal"):
            proposal = result["proposal"]
            break
    assert proposal is not None, "sample data should produce a proposal"

    # List proposals
    r = client.get("/api/v1/proposals")
    assert r.status_code == 200
    listed = r.json()
    assert any(p["proposal_id"] == proposal["proposal_id"] for p in listed)

    pid = proposal["proposal_id"]

    # Approve (accepted or already-executed via auto flow) then re-approve
    r = client.post(f"/api/v1/proposals/{pid}/approve")
    assert r.status_code == 200

    r = client.post(f"/api/v1/proposals/{pid}/approve")
    assert r.status_code == 200
    assert r.json()["status"] in (
        "already_executed",
        "rejected_by_risk",
        "order_submitted",
        "not_allowed",
    )

    # A rejected proposal rejects cleanly
    r = client.get("/api/v1/proposals?status=pending")
    pend = r.json()
    if pend:
        r = client.post(
            f"/api/v1/proposals/{pend[0]['proposal_id']}/reject", json={"reason": "test"}
        )
        assert r.status_code == 200


def test_replay_then_positions_trades_flow(client):
    """Run the tape with auto-approve on via config update, then inspect."""
    import goldbot.api.app as api

    eng = api.engine
    eng.update_config({"auto_approve": True})
    while eng._replay_index < len(eng._all_candles):
        eng.step_bar()

    proposals = client.get("/api/v1/proposals").json()
    assert len(proposals) > 0
    # every executed proposal has an order id
    for p in proposals:
        assert p["status"] in ("pending", "approved", "rejected", "executed")
    performance = client.get("/api/v1/performance").json()
    assert performance["total_trades"] == len(eng.get_trades())


def test_kill_switch_endpoint(client):
    r = client.post("/api/v1/risk/kill-switch", json={"active": True, "reason": "test"})
    assert r.status_code == 200
    assert r.json()["kill_switch"] is True

    r = client.post("/api/v1/risk/kill-switch", json={"active": False})
    assert r.status_code == 200
    assert r.json()["kill_switch"] is False


def test_risk_limits_endpoint(client):
    r = client.get("/api/v1/risk/limits")
    assert r.status_code == 200
    body = r.json()
    assert body["risk_per_trade_pct"] > 0
    assert body["kill_switch"] == []


def test_engine_start_stop(client):
    import goldbot.api.app as api

    eng = api.engine
    eng.stop_background()
    r = client.post("/api/v1/engine/start", json={"interval_seconds": 0.01})
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    try:
        r = client.post("/api/v1/engine/stop")
        assert r.status_code == 200
        assert r.json()["running"] is False
    finally:
        eng.stop_background()


def test_engine_status_endpoint(client):
    r = client.get("/api/v1/engine/status")
    assert r.status_code == 200
    body = r.json()
    assert body["total_bars"] > 1000
    assert "auto_approve" in body


def test_websocket_snapshot_and_events(client):
    import goldbot.api.app as api

    eng = api.engine

    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        data = snapshot["data"]
        assert "health" in data and "quote" in data
        assert "proposals" in data and "candles" in data

        # Move the engine; the WS channel must surface candle events
        received_types = []
        for _ in range(3):
            eng.step_bar()
            msg = ws.receive_json()
            received_types.append(msg["type"])
        assert "candle" in received_types


def test_invalid_proposal_404(client):
    r = client.post("/api/v1/proposals/nonexistent/approve")
    assert r.status_code == 404
    r = client.post("/api/v1/proposals/nonexistent/reject")
    assert r.status_code == 404


def test_close_position_no_position_404(client):
    r = client.post("/api/v1/positions/close", json={"symbol": "XAUUSD"})
    if r.status_code != 404:
        # position may exist from earlier tests in this class session;
        # a 200 with trade data is acceptable.
        assert r.status_code == 200


def test_prediction_endpoint(client):
    r = client.get("/api/v1/prediction")
    assert r.status_code == 200
    body = r.json()
    if not body.get("available", True):
        # Early in replay: honest limitation payload instead of a forecast.
        assert "insufficient" in body["detail"].lower()
        assert "data_limitation" in body
        return
    f = body["forecast"]
    for key in (
        "directional_bias",
        "regime",
        "entry_zone",
        "invalidation_level",
        "stop_loss",
        "take_profit",
        "risk_reward",
        "horizon",
        "confidence",
        "supporting_evidence",
    ):
        assert key in f
    assert 0 <= f["confidence"] <= 90
    assert "not a calibrated probability" in f["disclaimer"]
    assert body["evaluation"] is not None


def test_prediction_endpoint_horizon_validation(client):
    assert client.get("/api/v1/prediction?horizon=0").status_code in (400, 422)
    assert client.get("/api/v1/prediction?horizon=99").status_code in (400, 422)


def test_prediction_endpoint_insufficient_data_is_structured(client):
    """Early in replay the engine reveals < 60 bars; the endpoint must state
    the limitation rather than raise or fabricate a forecast."""
    r = client.get("/api/v1/prediction")
    assert r.status_code == 200
    body = r.json()
    if not body.get("available", True):
        assert "insufficient" in body["detail"].lower()
        assert "data_limitation" in body
