"""OANDA v20 adapter tests against a fake HTTP transport (no network)."""

import pytest

from goldbot.core.exceptions import GoldBotError
from goldbot.core.models import OrderSide, OrderStatus, OrderType
from goldbot.execution.oanda import OandaBrokerAdapter


class FakeOanda:
    """Scripted v20 responses."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.responses: dict[tuple[str, str], tuple[int, dict]] = {
            ("GET", "/v3/accounts/ACC/summary"): (
                200,
                {
                    "account": {
                        "NAV": "10000.00",
                        "balance": "9900.00",
                        "marginAvailable": "8000.00",
                        "marginUsed": "1000.00",
                        "unrealizedPL": "100.00",
                        "openTradeCount": 1,
                        "pendingOrderCount": 0,
                        "currency": "USD",
                        "id": "ACC",
                    }
                },
            ),
            ("GET", "/v3/accounts/ACC"): (
                200,
                {
                    "account": {
                        "id": "ACC",
                        "currency": "USD",
                        "balance": "9900.00",
                        "marginAvailable": "8000.00",
                        "marginUsed": "1000.00",
                        "unrealizedPL": "100.00",
                        "openTradeCount": 1,
                        "pendingOrderCount": 0,
                    }
                },
            ),
            ("GET", "/v3/accounts/ACC/positions"): (
                200,
                {
                    "positions": [
                        {
                            "instrument": "XAU_USD",
                            "long": {
                                "units": "150",
                                "averagePrice": "1950.00",
                                "unrealizedPL": "25.00",
                            },
                            "short": {"units": "0"},
                        }
                    ]
                },
            ),
            ("GET", "/v3/accounts/ACC/pendingOrders"): (
                200,
                {
                    "orders": [
                        {
                            "id": "99",
                            "type": "LIMIT",
                            "instrument": "XAU_USD",
                            "units": "100",
                            "price": "1900.00",
                            "state": "PENDING",
                            "clientExtensions": {"id": "goldbot-abc"},
                        }
                    ]
                },
            ),
            ("GET", "/v3/accounts/ACC/orders/99"): (
                200,
                {"order": {"id": "99", "state": "PENDING"}},
            ),
            ("GET", "/v3/accounts/ACC/orders"): (
                200,
                {"orders": [{
                    "id": "99", "type": "LIMIT", "state": "PENDING",
                    "units": "100", "clientExtensions": {"id": "goldbot-abc"},
                }]},
            ),
        }

    def __call__(self, method: str, url: str, headers: dict, body: dict | None):
        path = url.split("api-fx", 1)[1].split(".oanda.com", 1)[1].split("?", 1)[0]
        self.calls.append((method, path))
        if (method, path) in self.responses:
            return self.responses[(method, path)]
        if method == "POST" and path == "/v3/accounts/ACC/orders":
            return (
                201,
                {
                    "orderCreateTransaction": {"id": "42", "instrument": "XAU_USD"},
                    "orderFillTransaction": {"price": "1951.25", "id": "43"},
                },
            )
        if method == "PUT" and path.endswith("/cancel"):
            return (200, {"orderCancelTransaction": {"id": "50"}})
        if method == "PUT" and path.endswith("/close"):
            return (200, {"longOrderCreateTransaction": {"id": "60"}})
        return (404, {"errorMessage": "not found"})


@pytest.fixture()
def adapter() -> OandaBrokerAdapter:
    fake = FakeOanda()
    adapter = OandaBrokerAdapter(
        account_id="ACC",
        api_token="test-token",
        environment="practice",
        http=fake,
    )
    adapter._fake = fake
    return adapter


def test_invalid_environment_rejected():
    with pytest.raises(GoldBotError, match="environment"):
        OandaBrokerAdapter(account_id="ACC", api_token="t", environment="demo2")


def test_missing_credentials_rejected():
    with pytest.raises(GoldBotError, match="account_id"):
        OandaBrokerAdapter(account_id="", api_token="t")


def test_account_summary(adapter):
    summary = adapter.get_account_summary()
    assert summary["balance"] == 9900.0
    assert summary["available_margin"] == 8000.0
    assert summary["environment"] == "practice"
    assert summary["broker"] == "oanda"


def test_bearer_token_used_and_not_logged(adapter):
    summary = adapter.get_account_summary()
    assert summary["balance"] > 0  # request went through


def test_market_order_fills(adapter):
    order = adapter.send_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=1.0,
        stop_loss=1940.0,
        take_profit=1990.0,
    )
    assert order.status == OrderStatus.FILLED
    assert order.fill_price == 1951.25
    assert order.order_id == "42"
    # clientExtensions id present in the body, units converted 1 lot = 100
    method, path = adapter._fake.calls[-1]
    assert path == "/v3/accounts/ACC/orders"


def test_order_body_contains_stop_loss(adapter):
    captured: dict = {}

    def spy(method, url, headers, body):
        captured["body"] = body
        return FakeOanda()(method, url, headers, body)

    adapter._http = spy
    adapter.send_order(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        volume=0.5,
        stop_loss=1960.0,
    )
    order = captured["body"]["order"]
    assert order["units"] == "-50"  # sell = negative units
    assert order["stopLossOnFill"]["price"] == "1960.00000"
    assert order["clientExtensions"]["id"].startswith("goldbot-")


def test_limit_order_requires_price(adapter):
    with pytest.raises(GoldBotError, match="price"):
        adapter.send_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            volume=1.0,
            price=None,
        )


def test_wrong_symbol_rejected(adapter):
    with pytest.raises(GoldBotError, match="bound to"):
        adapter.send_order(
            symbol="EURUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            volume=1.0,
        )


def test_rejected_order_maps_to_status(adapter):
    adapter._http = lambda m, u, h, b: (400, {"errorMessage": "insufficient margin"})
    order = adapter.send_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=1.0,
    )
    assert order.status == OrderStatus.REJECTED


def test_get_positions_converts_units_to_lots(adapter):
    positions = adapter.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "XAUUSD"
    assert pos.side == OrderSide.BUY
    assert pos.volume == pytest.approx(1.5)  # 150 units / 100
    assert pos.entry_price == pytest.approx(1950.0)


def test_reconciliation_detects_mismatch(adapter):
    report = adapter.reconcile(local_open_volume_lots=2.0)
    assert report["agreed"] is False
    assert report["difference_lots"] == pytest.approx(0.5)
    report_ok = adapter.reconcile(local_open_volume_lots=1.5)
    assert report_ok["agreed"] is True


def test_pending_orders_and_history(adapter):
    pending = adapter.get_pending_orders()
    assert pending[0]["order_id"] == "99"
    history = adapter.get_order_history()
    assert isinstance(history, list)


def test_health_check_true_and_false(adapter):
    assert adapter.health_check() is True
    adapter._http = lambda m, u, h, b: (500, {"errorMessage": "boom"})
    assert adapter.health_check() is False
