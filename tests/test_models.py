"""Core domain model tests."""

from datetime import datetime, timezone

import pytest

from goldbot.core.models import (
    InstrumentMetadata,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Signal,
    SignalDirection,
)
from tests.conftest import make_candle


def test_candle_bullish_bearish_and_shadows():
    c = make_candle(0, open_=100.0, close=110.0, high=115.0, low=95.0)
    assert c.is_bullish and not c.is_bearish
    assert c.body_size == pytest.approx(10.0)
    assert c.upper_shadow == pytest.approx(5.0)
    assert c.lower_shadow == pytest.approx(5.0)


def test_candle_repr_contains_key_fields():
    c = make_candle(0)
    text = repr(c)
    for token in ("XAUUSD", "15m", "1950.0"):
        assert token in text


def test_quote_derived_values():
    q = Quote(bid=10.0, ask=10.5)
    assert q.spread == pytest.approx(0.5)
    assert q.mid_price == pytest.approx(10.25)


def test_signal_direction_parsing():
    assert SignalDirection.from_string("LONG") == SignalDirection.LONG
    assert SignalDirection.from_string("BUY") == SignalDirection.LONG
    assert SignalDirection.from_string("sell") == SignalDirection.SHORT
    assert SignalDirection.from_string("banana") == SignalDirection.FLAT


def test_signal_id_is_deterministic_per_inputs():
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    a = Signal("XAUUSD", SignalDirection.LONG, ts, 1950.0, 5.0, 2.0, "15m")
    b = Signal("XAUUSD", SignalDirection.LONG, ts, 1950.0, 5.0, 2.0, "15m")
    assert a.signal_id == b.signal_id


def test_order_enum_coercion_and_lifecycle():
    o = Order(
        order_id="x",
        symbol="XAUUSD",
        side="buy",
        order_type="market",
        volume=1.0,
        status="filled",
    )
    assert o.side == OrderSide.BUY
    assert o.order_type == OrderType.MARKET
    assert o.status == OrderStatus.FILLED
    assert o.is_filled and o.is_complete
    o.status = OrderStatus.PENDING
    assert not o.is_complete


def test_position_pnl_percent_long_and_short():
    long_pos = Position("XAUUSD", OrderSide.BUY, 1.0, 1900.0, current_price=1950.0)
    assert long_pos.pnl_percent > 0
    short_pos = Position("XAUUSD", OrderSide.SELL, 1.0, 1950.0, current_price=1900.0)
    assert short_pos.pnl_percent > 0
    flat = Position("XAUUSD", OrderSide.BUY, 1.0, 0.0, current_price=10.0)
    assert flat.pnl_percent == 0.0


def test_instrument_metadata_verification_flag():
    m = InstrumentMetadata(symbol="XAUUSD", verified=True)
    assert m.is_verified
    m.verified = False
    assert not m.is_verified
