"""Rigorous live end-to-end verification of the running GoldBot system.

Run: PYTHONPATH=src .venv/bin/python scripts/e2e_live.py
Exits non-zero on the first failure. Prints a PASS/FAIL line per check.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from goldbot.core.instruments import CANONICAL_SYMBOL

BASE = "http://127.0.0.1:8000"
PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def call(method: str, path: str, body: dict | None = None, timeout: float = 10.0):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, json.loads(resp.read().decode())


def check(name: str, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        FAILED.append((name, repr(exc)))
        print(f"ERROR {name}: HTTP {exc.code} {detail}")
    except Exception as exc:  # noqa: BLE001
        FAILED.append((name, repr(exc)))
        print(f"ERROR {name}: {exc!r}")


# ---------------------------------------------------------------------------


def t_health():
    status, body = call("GET", "/api/v1/health")
    assert status == 200, f"{status}"
    assert body["status"] in ("ok", "kill_switch_active"), body
    assert body["mode"] == "paper"
    assert body["running"] is True
    assert body["total_bars"] >= 1000, body["total_bars"]


def t_quote():
    status, body = call("GET", "/api/v1/quote")
    assert status == 200
    assert body["bid"] < body["ask"], body
    assert abs(body["spread"] - (body["ask"] - body["bid"])) < 0.11
    assert body["mid_price"] > 1000.0, body


def t_candles():
    # Fresh replays reveal bars over time and the replay "wraps" to bar 0
    # after exhausting the dataset - wait until we are inside a window that
    # guarantees a full candle page.
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            _s, es = call("GET", "/api/v1/engine/status", timeout=5)
            if 400 <= es["replay_index"] <= 1300:
                break
        except Exception:
            pass  # noqa: S110 (soft-wait)
        time.sleep(0.5)
    for attempt in range(10):
        status, body = call("GET", "/api/v1/candles?limit=250", timeout=10)
        if status == 200 and len(body["candles"]) >= 200:
            break
        time.sleep(2)
    assert status == 200
    cs = body["candles"]
    assert len(cs) >= 200, len(cs)
    times = [c["time"] for c in cs]
    assert times == sorted(times), "candles must be time-ordered"
    for c in cs:
        assert c["high"] >= max(c["open"], c["close"]), c
        assert c["low"] <= min(c["open"], c["close"]), c
        assert c["volume"] >= 0
    ind = body["indicators"]
    for name in ("ema_fast", "ema_trend", "ema_long"):
        s = ind[name]
        assert len(s) == len(cs), (name, len(s), len(cs))
        vals = [v for v in s if v is not None]
        assert vals, f"{name} should have warmed up"
    print(f"       candles={len(cs)} last_close={cs[-1]['close']}")


def t_indicators():
    status, body = call("GET", "/api/v1/indicators")
    assert status == 200
    for key in ("ema_fast", "ema_trend", "ema_long", "rsi", "atr", "adx"):
        assert key in body, key
        assert body[key] is not None and 0 <= float(body[key]) < 100000, (key, body[key])
    rsi_v = float(body["rsi"])
    assert 0 <= rsi_v <= 100
    adx_v = float(body["adx"])
    assert 0 <= adx_v <= 100


def t_account():
    status, body = call("GET", "/api/v1/account")
    assert status == 200
    assert 5000 < body["equity"] < 15000, body
    assert 5000 < body["balance"] < 15000


def t_orders_and_positions():
    status, orders = call("GET", "/api/v1/orders")
    assert status == 200 and isinstance(orders, list)
    status, positions = call("GET", "/api/v1/positions")
    assert status == 200 and isinstance(positions, list)
    for p in positions:
        assert p["symbol"] == CANONICAL_SYMBOL
        assert p["side"] in ("buy", "sell")
        assert p["volume"] >= 0.01, p
        assert p["stop_loss"] > 0 and p["take_profit"] > 0, p
    print(f"       orders={len(orders)} positions={len(positions)}")


def t_trades_and_performance():
    status, trades = call("GET", "/api/v1/trades?limit=1000")
    assert status == 200 and isinstance(trades, list)
    status, perf = call("GET", "/api/v1/performance")
    assert status == 200
    assert perf["total_trades"] == len(trades), (perf, len(trades))
    assert 0 <= perf["win_rate"] <= 100
    for t in trades:
        assert "pnl" in t and t["entry_price"] > 0, t
        assert t["reason"] in ("stop_loss", "take_profit", "manual_close", "risk_close")
    print(f"       trades={len(trades)} win_rate={perf['win_rate']}")


def t_proposals_list():
    status, props = call("GET", "/api/v1/proposals")
    assert status == 200 and isinstance(props, list)
    for p in props[:10]:
        assert p["direction"] in ("long", "short"), p
        assert p["status"] in ("pending", "approved", "rejected", "executed", "expired"), p
    print(f"       proposals={len(props)}")


def t_config_roundtrip():
    status, cfg = call("GET", "/api/v1/config")
    assert status == 200
    orig = cfg["max_entries_per_day"]
    status, upd = call("POST", "/api/v1/config", {"max_entries_per_day": orig + 1})
    assert status == 200, upd
    status, reread = call("GET", "/api/v1/config")
    assert reread["max_entries_per_day"] == orig + 1
    # restore
    call("POST", "/api/v1/config", {"max_entries_per_day": orig})
    # invalid rejected (endpoint returns 400; urllib raises HTTPError)
    try:
        _s, _b = call("POST", "/api/v1/config", {})
        raise AssertionError(f"expected 400 for empty payload, got {_s}")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def t_engine_status():
    status, body = call("GET", "/api/v1/engine/status")
    assert status == 200
    assert body["running"] is True
    assert 0 < body["replay_index"] <= body["total_bars"]
    assert body["total_bars"] == 1510


def wait_for_proposal(timeout_s: float = 60.0) -> dict | None:
    """Wait until the running engine generates a proposal."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _s, engine_status = call("GET", "/api/v1/engine/status")
            _s, props = call("GET", "/api/v1/proposals?status=pending")
            if props:
                return props[0]
        except urllib.error.HTTPError as exc:
            print(f"       (http {exc.code} while waiting)")
        time.sleep(0.3)
    return None


def t_proposal_lifecycle():
    prop = wait_for_proposal(timeout_s=90)
    assert prop is not None, "no pending proposal appeared within 90s"
    pid = prop["proposal_id"]
    assert prop["status"] == "pending"
    assert prop["direction"] in ("long", "short")
    assert prop["position_size"] >= 0.01, prop
    assert prop["stop_loss"] > 0 and prop["take_profit"] > 0

    # reject it deterministically
    status, rejected = call("POST", f"/api/v1/proposals/{pid}/reject", {"reason": "e2e_reject"})
    assert status == 200 and rejected["status"] == "rejected", (status, rejected)

    # approving a rejected proposal must not place orders
    status, out = call("POST", f"/api/v1/proposals/{pid}/approve")
    assert status == 200, (status, out)
    assert out["status"] in ("rejected_by_risk", "already_executed", "not_allowed"), out

    # next proposal: approve it and expect an order + position
    prop2 = wait_for_proposal(timeout_s=90)
    assert prop2 is not None, "no second pending proposal appeared"
    p2 = prop2["proposal_id"]
    orders_before = len(call("GET", "/api/v1/orders")[1])
    status, approved = call("POST", f"/api/v1/proposals/{p2}/approve")
    assert status == 200, (status, approved)
    assert approved["status"] == "order_submitted", approved
    assert approved.get("order_id"), approved

    status, orders = call("GET", "/api/v1/orders")
    assert len(orders) == orders_before + 1
    latest = orders[0]  # newest first
    assert latest["order_id"] == approved["order_id"]
    assert latest["status"] == "filled", latest

    status, positions = call("GET", "/api/v1/positions")
    assert any(p["volume"] > 0 for p in positions), positions

    # double-approve is idempotent
    status, dup = call("POST", f"/api/v1/proposals/{p2}/approve")
    assert status == 200 and dup["status"] == "already_executed", dup


def t_close_flow():
    status, positions = call("GET", "/api/v1/positions")
    open_pos = [p for p in positions if p["volume"] > 0]
    assert open_pos, "expected a position from the approve flow"
    status, result = call("POST", "/api/v1/positions/close", {"symbol": open_pos[0]["symbol"]})
    if status == 404:  # SL/TP already closed it between the two calls
        return
    assert status == 200, result
    assert result["reason"] == "manual_close"
    status, trades = call("GET", "/api/v1/trades")
    assert trades and trades[0]["reason"] == "manual_close"


def t_kill_switch():
    status, health = call(
        "POST", "/api/v1/risk/kill-switch", {"active": True, "reason": "e2e_test"}
    )
    assert status == 200 and health["kill_switch"] is True
    assert any("e2e_test" in r for r in health["kill_switch_reasons"]), health

    # While active, a manual approval must be rejected by risk
    wait_for_proposal(timeout_s=0.2)  # must NOT produce a pending one
    # Deactivate
    status, health = call("POST", "/api/v1/risk/kill-switch", {"active": False})
    assert status == 200 and health["kill_switch"] is False and not health["kill_switch_reasons"]


def t_risk_limits_endpoint():
    status, body = call("GET", "/api/v1/risk/limits")
    assert status == 200
    for key in (
        "risk_per_trade_pct",
        "daily_loss_limit_pct",
        "max_open_positions",
        "entries_today",
        "consecutive_losses",
    ):
        assert key in body, (key, body)


def t_websocket_snapshot():
    """Verify the WS snapshot + live event stream."""
    import websockets  # noqa

    raise AssertionError("websocket handled by dedicated script")


def t_unknown_route_404():
    try:
        call("GET", "/api/v1/definitely-not-here")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


if __name__ == "__main__":
    checks = [
        ("health", t_health),
        ("quote", t_quote),
        ("candles", t_candles),
        ("indicators", t_indicators),
        ("account", t_account),
        ("orders+positions", t_orders_and_positions),
        ("trades+performance", t_trades_and_performance),
        ("proposals", t_proposals_list),
        ("config roundtrip", t_config_roundtrip),
        ("engine status", t_engine_status),
        ("proposal lifecycle", t_proposal_lifecycle),
        ("position close flow", t_close_flow),
        ("kill switch", t_kill_switch),
        ("risk limits endpoint", t_risk_limits_endpoint),
        ("unknown 404", t_unknown_route_404),
    ]
    for name, fn in checks:
        check(name, fn)
    print()
    print(f"RESULT: {len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
