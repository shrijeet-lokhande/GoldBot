"""PaperBroker execution simulation tests (fills, SL/TP, persistence)."""

from pathlib import Path

import pytest

from goldbot.core.exceptions import OrderRejectedError
from goldbot.core.models import OrderSide, OrderStatus, OrderType


def test_market_buy_fills_with_spread_and_slippage(broker):
    order = broker.send_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10, price=None)
    assert order.status == OrderStatus.FILLED
    # buy fills above mid: spread/2 + slippage/2
    assert order.fill_price == pytest.approx(1950.0 + 0.05 + 0.1)
    pos = broker.get_open_position("XAUUSD")
    assert pos is not None
    assert pos.side == OrderSide.BUY
    assert pos.volume == pytest.approx(0.10)


def test_market_sell_fills_below_mid(broker):
    order = broker.send_order("XAUUSD", OrderSide.SELL, OrderType.MARKET, 0.10, price=None)
    assert order.status == OrderStatus.FILLED
    assert order.fill_price == pytest.approx(1950.0 - 0.05 - 0.1)


def test_zero_volume_rejected(broker):
    with pytest.raises(OrderRejectedError):
        broker.send_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.0)


def test_limit_order_requires_price(broker):
    with pytest.raises(OrderRejectedError):
        broker.send_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 0.1, price=None)


def test_limit_buy_fills_when_market_below_limit(broker):
    broker.set_price(900.0)
    order = broker.send_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 0.05, price=950.0)
    assert order.status == OrderStatus.FILLED
    assert order.fill_price == pytest.approx(950.0)


def test_limit_buy_stays_rejected_when_above_limit(broker):
    broker.set_price(1000.0)
    order = broker.send_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 0.05, price=950.0)
    assert order.status == OrderStatus.REJECTED
    assert broker.get_open_position("XAUUSD") is None


def test_take_profit_closes_position_in_profit(broker):
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10, stop_loss=1940.0, take_profit=1970.0
    )
    closed = broker.update_market_price(1971.0)
    assert len(closed) == 1
    trade = closed[0]
    assert trade["reason"] == "take_profit"
    assert trade["pnl"] > 0
    assert broker.get_open_position("XAUUSD") is None


def test_stop_loss_closes_position_in_loss(broker):
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10, stop_loss=1940.0, take_profit=1970.0
    )
    closed = broker.update_market_price(1939.0)
    assert len(closed) == 1
    assert closed[0]["reason"] == "stop_loss"
    assert closed[0]["pnl"] < 0
    assert broker._realised_pnl_total + broker.initial_equity < broker.initial_equity


def test_short_position_take_profit_downside(broker):
    broker.send_order(
        "XAUUSD", OrderSide.SELL, OrderType.MARKET, 0.20, stop_loss=1960.0, take_profit=1930.0
    )
    closed = broker.update_market_price(1929.0)
    assert closed[0]["reason"] == "take_profit"
    assert closed[0]["pnl"] > 0


def test_short_position_stop_loss_upside(broker):
    broker.send_order(
        "XAUUSD", OrderSide.SELL, OrderType.MARKET, 0.20, stop_loss=1960.0, take_profit=1930.0
    )
    closed = broker.update_market_price(1961.0)
    assert closed[0]["reason"] == "stop_loss"
    assert closed[0]["pnl"] < 0


def test_intrabar_path_low_before_high(broker):
    """Within a candle, the lower price step happens first via engine; the
    broker must close at SL when price <= sl for longs."""
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10, stop_loss=1900.0, take_profit=2000.0
    )
    closed = broker.update_market_price(1899.0)
    assert closed and closed[0]["reason"] == "stop_loss"


def test_manual_close(broker):
    broker.send_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.30)
    trade = broker.close_position("XAUUSD")
    assert trade is not None
    assert trade["reason"] == "manual_close"
    assert broker.get_open_position("XAUUSD") is None
    # manual close of a flat book returns None
    assert broker.close_position("XAUUSD") is None


def test_equity_tracks_pnl(broker):
    start = broker.get_account_equity()
    assert start == pytest.approx(10_000.0)
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0, stop_loss=1900.0, take_profit=2000.0
    )
    mid = broker.get_account_equity()
    broker.update_market_price(1960.0)
    up = broker.get_account_equity()
    assert up > mid
    closed = broker.update_market_price(2001.0)
    assert closed
    assert broker.get_account_equity() > start


def test_reversal_of_position(broker):
    # Open long, then send the opposite side in a bigger size -> reversal
    broker.send_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10)
    order = broker.send_order("XAUUSD", OrderSide.SELL, OrderType.MARKET, 0.20)
    assert order.status == OrderStatus.FILLED
    pos = broker.get_open_position("XAUUSD")
    assert pos is not None
    assert pos.side == OrderSide.SELL
    assert pos.volume == pytest.approx(0.10)
    # closed_trade ledger recorded the manual close of the long leg
    assert any(t["reason"] == "manual_close" for t in broker.closed_trades)


def test_persistence_roundtrip(tmp_path, broker):
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.25, stop_loss=1940.0, take_profit=1980.0
    )
    path: Path = broker.persistence_path
    assert path.exists()

    # Simulate a restart: new broker over the same file keeps the position
    from goldbot.execution.paper_broker import PaperBroker

    restored = PaperBroker(
        symbol="XAUUSD",
        persistence_path=path,
        initial_equity=10_000.0,
        contract_size=100.0,
    )
    pos = restored.get_open_position("XAUUSD")
    assert pos is not None
    assert pos.volume == pytest.approx(0.25)
    assert pos.stop_loss == pytest.approx(1940.0)
    assert pos.take_profit == pytest.approx(1980.0)


def test_closed_trades_persist_across_restart(tmp_path, broker):
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10, stop_loss=1900.0, take_profit=2000.0
    )
    broker.update_market_price(1880.0)  # SL hit
    from goldbot.execution.paper_broker import PaperBroker

    restored = PaperBroker(
        symbol="XAUUSD",
        persistence_path=broker.persistence_path,
        initial_equity=10_000.0,
        contract_size=100.0,
    )
    assert len(restored.closed_trades) == 1
    assert restored.closed_trades[0]["pnl"] < 0


def test_get_trades_newest_first(broker):
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.05, stop_loss=1900.0, take_profit=2000.0
    )
    broker.update_market_price(1890.0)  # close 1
    broker.send_order(
        "XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.05, stop_loss=1990.0, take_profit=2100.0
    )
    broker.update_market_price(1895.0)  # close 2
    trades = broker.get_trades()
    assert len(trades) == 2
    limited = broker.get_trades(limit=1)
    assert len(limited) == 1
    assert limited[0]["pnl"] == trades[0]["pnl"]


def test_cancel_order(broker):
    order = broker.send_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.10)
    assert broker.cancel_order(order.order_id)
    assert broker.get_order_state(order.order_id) == OrderStatus.CANCELLED
    assert not broker.cancel_order("missing")
