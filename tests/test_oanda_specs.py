"""OANDA real contract-spec tests (scripted transport, no network)."""

import pytest

from goldbot.core.exceptions import GoldBotError, MetadataError
from goldbot.core.models import SignalDirection
from goldbot.execution.oanda import (
    UNITS_PER_LOT,
    OandaBrokerAdapter,
    instrument_spec_from_oanda,
)
from goldbot.risk.position_sizing import calculate_position_size

# Realistic OANDA v20 instrument object for XAU_USD (practice accounts).
XAU_USD_DETAILS = {
    "name": "XAU_USD",
    "type": "METAL",
    "displayName": "Gold/USD",
    "pipLocation": -1,
    "displayPrecision": 3,
    "tradeUnitsPrecision": 0,
    "minimumTradeSize": "1",
    "maximumOrderUnits": "15000",
    "marginRate": "0.02",
}


def make_adapter(http):
    return OandaBrokerAdapter(
        account_id="101-004-1-001",
        api_token="not-a-real-token",  # noqa: S106 — scripted transport, no network
        environment="practice",
        http=http,
    )


def test_spec_from_oanda_details():
    spec = instrument_spec_from_oanda(XAU_USD_DETAILS, "XAUUSD")
    assert spec.verified is True
    assert spec.venue == "OANDA"
    assert spec.quote_currency == "USD"
    # displayPrecision=3 -> tick = 0.001
    assert spec.tick_size == pytest.approx(0.001)
    assert spec.tick_value == pytest.approx(0.001 * UNITS_PER_LOT)
    # 1 GoldBot lot = 100 oz; minimumTradeSize=1 unit -> 0.01 lots
    assert spec.min_volume == pytest.approx(0.01)
    assert spec.max_volume == pytest.approx(150.0)
    # units precision 0 -> step = 1 unit = 0.01 lots
    assert spec.volume_step == pytest.approx(0.01)
    assert spec.margin_rate == pytest.approx(0.02)


@pytest.mark.parametrize(
    "remove_field",
    ["displayPrecision", "tradeUnitsPrecision", "minimumTradeSize", "maximumOrderUnits"],
)
def test_spec_rejects_missing_fields(remove_field):
    details = dict(XAU_USD_DETAILS)
    details.pop(remove_field)
    with pytest.raises(MetadataError, match="missing required fields"):
        instrument_spec_from_oanda(details, "XAUUSD")


def test_spec_rejects_inconsistent_bounds():
    details = dict(XAU_USD_DETAILS)
    details["minimumTradeSize"] = "20000"  # above maximumOrderUnits
    with pytest.raises(MetadataError, match="exceeds maximumOrderUnits"):
        instrument_spec_from_oanda(details, "XAUUSD")


def test_get_instrument_spec_via_scripted_transport():
    responses = {
        "GET /v3/accounts/101-004-1-001/instruments": (
            200,
            {"instruments": [XAU_USD_DETAILS]},
        ),
        "GET /v3/accounts/101-004-1-001": (
            200,
            {"account": {"id": "101-004-1-001", "currency": "USD", "balance": "10000"}},
        ),
    }

    def http(method, url, headers, body):
        key = f"{method} {url.split('?')[0].replace('https://api-fxpractice.oanda.com', '')}"
        return responses[key]

    adapter = make_adapter(http)
    spec = adapter.get_instrument_spec("XAUUSD")
    assert spec.verified
    assert spec.symbol == "XAUUSD"
    # USD account == quote currency -> no conversion annotation needed.
    assert "account_currency" not in spec.source


def test_get_instrument_spec_unknown_instrument_rejected():
    responses = {
        "GET /v3/accounts/101-004-1-001/instruments": (200, {"instruments": []}),
        "GET /v3/accounts/101-004-1-001": (
            200,
            {"account": {"id": "x", "currency": "USD", "balance": "1"}},
        ),
    }

    def http(method, url, headers, body):
        key = f"{method} {url.split('?')[0].replace('https://api-fxpractice.oanda.com', '')}"
        return responses[key]

    adapter = make_adapter(http)
    with pytest.raises(GoldBotError, match="does not list instrument"):
        adapter.get_instrument_spec("XAUUSD")


def test_account_currency_conversion_rate():
    responses = {
        "GET /v3/accounts/101-004-1-001/instruments": (
            200,
            {"instruments": [XAU_USD_DETAILS]},
        ),
        "GET /v3/accounts/101-004-1-001": (
            200,
            {"account": {"id": "x", "currency": "EUR", "balance": "9000"}},
        ),
        # First candidate pair is (account, quote) = EUR_USD, price = USD per
        # EUR = 1/0.9; the adapter inverts it to EUR per USD = 0.9.
        "GET /v3/instruments/EUR_USD/candles": (
            200,
            {
                "candles": [
                    {
                        "complete": True,
                        "time": "0",
                        "mid": {"o": "1.11111", "h": "1.11111", "l": "1.11111", "c": "1.11111"},
                    }
                ]
            },
        ),
    }

    def http(method, url, headers, body):
        key = f"{method} {url.split('?')[0].replace('https://api-fxpractice.oanda.com', '')}"
        return responses[key]

    adapter = make_adapter(http)
    rate = adapter.get_quote_to_account_rate("USD", "EUR")
    # EUR_USD close 1.111111 = USD per EUR; inverted -> EUR per USD = 0.9.
    assert rate == pytest.approx(0.9, rel=1e-5)


def test_unavailable_conversion_rate_rejects():
    def http(method, url, headers, body):
        return 404, {}

    adapter = make_adapter(http)
    with pytest.raises(MetadataError, match="Cannot determine conversion rate"):
        adapter.get_quote_to_account_rate("USD", "XYZ")


def test_sizing_uses_conversion_rate():
    spec = instrument_spec_from_oanda(XAU_USD_DETAILS, "XAUUSD")
    base = calculate_position_size(
        equity=10_000.0,
        risk_per_trade_pct=1.0,  # $100 risk budget
        entry_price=2000.0,
        stop_price=1990.0,  # $10 stop distance
        instrument=spec,
        side=SignalDirection.LONG,
    )
    # cash risk per lot = stop distance (10) × 100 oz = $1000/lot
    # -> $100 budget = 0.1 lots
    assert base == pytest.approx(0.1)

    converted = calculate_position_size(
        equity=10_000.0,
        risk_per_trade_pct=1.0,
        entry_price=2000.0,
        stop_price=1990.0,
        instrument=spec,
        side=SignalDirection.LONG,
        quote_to_account_rate=0.5,  # account currency worth half
    )
    # value_per_lot = 50 -> cash risk/lot = $500 -> 0.2 lots
    assert converted == pytest.approx(0.2)


def test_sizing_rejects_non_positive_rate():
    spec = instrument_spec_from_oanda(XAU_USD_DETAILS, "XAUUSD")
    with pytest.raises(Exception, match="quote_to_account_rate"):
        calculate_position_size(
            equity=10_000.0,
            risk_per_trade_pct=1.0,
            entry_price=2000.0,
            stop_price=1990.0,
            instrument=spec,
            side=SignalDirection.LONG,
            quote_to_account_rate=0.0,
        )
