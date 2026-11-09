"""TrendPullbackStrategy signal logic tests."""

from datetime import datetime, timedelta, timezone

import pytest

from goldbot.strategies.trend_pullback import TrendPullbackStrategy
from tests.conftest import make_candle


class MarketData:
    """Minimal market context matching the engine's MarketContext shape."""

    def __init__(self, symbol="XAUUSD", entry_timeframe="15m", trend_timeframe="1h", candles=None):
        self.symbol = symbol
        self.entry_timeframe = entry_timeframe
        self.trend_timeframe = trend_timeframe
        self.candles = candles or {}


def indicators(**overrides):
    values = {
        "ema_fast": 1950.0,
        "ema_trend": 1955.0,
        "ema_long": 1945.0,
        "rsi": 55.0,
        "atr": 4.0,
        "adx": 30.0,
    }
    values.update(overrides)
    return {k: {"value": v} for k, v in values.items()}


@pytest.fixture()
def strategy():
    return TrendPullbackStrategy()


def long_context_completing_setup():
    """Entry candles where a completed bullish candle just pulled back to EMA fast."""
    base = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    prior = make_candle(
        0,
        open_=1950.0,
        high=1950.5,
        low=1949.4,
        close=1950.0,
    )
    prior.timestamp_utc = base
    recent = make_candle(
        1,
        open_=1950.0,
        high=1953.0,
        low=1949.6,
        close=1952.5,
    )
    recent.timestamp_utc = base + timedelta(minutes=15)
    return [prior, recent]


def test_long_setup_emits_signal(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    signal = strategy.generate_signal(md, indicators())
    assert signal is not None
    assert signal.direction == "long"
    assert signal.stop_distance == pytest.approx(4.0 * 1.5)
    # grow area check: reference price == recent close
    assert signal.reference_price == pytest.approx(1952.5)
    assert "bullish_candle_confirmed" in signal.reason_codes
    assert strategy.signals_emitted == 1


def test_duplicate_candle_suppressed(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    ind = indicators()
    assert strategy.generate_signal(md, ind) is not None
    # Same candles again -> the exact earlier candle is suppressed
    assert strategy.generate_signal(md, ind) is None


def test_downtrend_blocks_long(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    signal = strategy.generate_signal(md, indicators(ema_trend=1940.0, ema_long=1950.0))
    assert signal is None


def test_weak_adx_blocks(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    signal = strategy.generate_signal(md, indicators(adx=15.0))
    assert signal is None


def test_low_rsi_blocks_long(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    signal = strategy.generate_signal(md, indicators(rsi=30.0))
    assert signal is None


def test_bearish_candle_blocks_long(strategy):
    candles = long_context_completing_setup()
    candles[-1] = make_candle(1, open_=1951.0, high=1953.0, low=1948.0, close=1949.5)
    md = MarketData(candles={"15m": candles, "1h": [make_candle(0)]})
    assert strategy.generate_signal(md, indicators()) is None


def test_missing_pullback_blocks_long(strategy):
    # Both candles stay above EMA20 (1950) with no touch: no pullback.
    candles = [
        make_candle(0, open_=1952.0, high=1953.0, low=1951.2, close=1951.5),
        make_candle(1, open_=1951.5, high=1953.5, low=1951.6, close=1953.2),
    ]
    md = MarketData(candles={"15m": candles, "1h": [make_candle(0)]})
    assert strategy.generate_signal(md, indicators()) is None


def short_context_completing_setup():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    prior = make_candle(0, open_=1950.0, high=1950.6, low=1950.0, close=1950.0)
    prior.timestamp_utc = base
    recent = make_candle(1, open_=1950.0, high=1952.4, low=1947.0, close=1947.5)
    recent.timestamp_utc = base + timedelta(minutes=15)
    return [prior, recent]


def test_short_setup_emits_signal(strategy):
    md = MarketData(candles={"15m": short_context_completing_setup(), "1h": [make_candle(0)]})
    signal = strategy.generate_signal(
        md,
        indicators(ema_trend=1945.0, ema_long=1955.0, rsi=45.0),
    )
    assert signal is not None
    assert signal.direction == "short"
    assert "bearish_candle_confirmed" in signal.reason_codes


def test_duplicate_suppression_ignores_short_after_long_registered(strategy):
    """A no-signal long evaluation must not kill a subsequent short setup."""
    candles = short_context_completing_setup()
    md = MarketData(candles={"15m": candles, "1h": [make_candle(0)]})
    ind = indicators(ema_trend=1945.0, ema_long=1955.0, rsi=45.0)
    signal = strategy.generate_signal(md, ind)
    assert signal is not None and signal.direction == "short"


def test_missing_indicator_values_yields_none(strategy):
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    ind = indicators()
    ind["rsi"] = {"value": None}
    assert strategy.generate_signal(md, ind) is None


def test_insufficient_candles_yields_none(strategy):
    md = MarketData(candles={"15m": [], "1h": []})
    assert strategy.generate_signal(md, indicators()) is None


def test_incomplete_candle_blocked_by_candle_close_only(strategy):
    candles = long_context_completing_setup()
    candles[-1] = make_candle(1, complete=False)
    md = MarketData(candles={"15m": candles, "1h": [make_candle(0)]})
    assert strategy.generate_signal(md, indicators()) is None


def test_custom_parameters_overrides():
    strat = TrendPullbackStrategy(minimum_adx=40.0)
    md = MarketData(candles={"15m": long_context_completing_setup(), "1h": [make_candle(0)]})
    assert strat.generate_signal(md, indicators()) is None
    assert strat.generate_signal(md, indicators(adx=45.0)) is not None
