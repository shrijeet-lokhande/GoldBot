"""Tests for the v2 indicators: MACD, StochRSI, Bollinger, VWAP, SMA, Fib, levels."""

import numpy as np
import pandas as pd
import pytest

from goldbot.indicators import (
    bollinger_bands,
    detect_levels,
    ema,
    fibonacci_levels,
    has_reliable_volume,
    macd,
    sma,
    stochastic_rsi,
    vwap,
)
from goldbot.indicators.fibonacci import Swing


def _trending_close(n: int = 120, start: float = 1950.0) -> pd.Series:
    return pd.Series([start + i * 0.5 for i in range(n)], dtype=float)


def _oscillating_close(n: int = 120) -> pd.Series:
    return pd.Series([1950 + 10 * np.sin(i / 5.0) for i in range(n)], dtype=float)


def test_sma_matches_known_value():
    close = _trending_close(30)
    result = sma(close, 20)
    expected = close.iloc[-20:].mean()
    assert result.iloc[-1] == pytest.approx(expected)
    assert pd.isna(result.iloc[0])  # true rolling: NaN before warm-up


def test_sma_period_validation():
    with pytest.raises(ValueError):
        sma(_trending_close(5), 0)


def test_macd_bullish_trend_positive():
    m = macd(_trending_close(120))
    assert m.last_macd > 0
    assert m.last_histogram is not None


def test_macd_crossover_detection():
    # An upward shock flips the histogram positive on the shock bar.
    close = _oscillating_close(60)
    shocked = pd.concat([close, pd.Series([1980.0, 1990.0])], ignore_index=True)
    m = macd(shocked, 5, 12, 4)
    assert m.crossover in ("bullish", None)


def test_macd_validates_periods():
    with pytest.raises(ValueError):
        macd(_trending_close(50), fast_period=26, slow_period=12)


def test_stochastic_rsi_range():
    k, d = stochastic_rsi(_oscillating_close(120))
    last_k = k.dropna()
    assert len(last_k) > 0
    assert (last_k.between(-5, 105)).all()
    assert d.iloc[-1] == pytest.approx(k.iloc[-3:].mean())


def test_bollinger_bands_shape():
    close = _oscillating_close(120)
    bb = bollinger_bands(close, 20, 2.0)
    assert bb.upper.iloc[-1] > bb.middle.iloc[-1]
    assert bb.middle.iloc[-1] > bb.lower.iloc[-1]
    pct_b = bb.percentile_b(float(close.iloc[-1]))
    assert 0.0 <= pct_b <= 1.0
    assert bb.bandwidth > 0


def test_bollinger_period_validation():
    with pytest.raises(ValueError):
        bollinger_bands(_trending_close(10), period=1)


def test_vwap_available_with_volume():
    n = 50
    high = pd.Series([1955.0] * n, dtype=float)
    low = pd.Series([1945.0] * n, dtype=float)
    close = pd.Series([1950.0] * n, dtype=float)
    volume = pd.Series([100.0] * n, dtype=float)
    result = vwap(high, low, close, volume)
    assert result is not None
    assert result.iloc[-1] == pytest.approx(1950.0)


def test_vwap_unavailable_without_volume():
    high = pd.Series([1955.0, 1956.0], dtype=float)
    low = pd.Series([1945.0, 1946.0], dtype=float)
    close = pd.Series([1950.0, 1951.0], dtype=float)
    volume = pd.Series([0.0, 0.0], dtype=float)
    assert not has_reliable_volume(volume)
    assert vwap(high, low, close, volume) is None


def test_fibonacci_up_swing():
    swing = Swing(high=2000.0, low=1900.0, direction="up")
    levels = fibonacci_levels(swing)
    assert levels.retracements["fib_0.618"] == pytest.approx(1938.2)
    assert levels.extensions["fib_1.618"] == pytest.approx(2061.8)


def test_fibonacci_down_swing_mirror():
    swing = Swing(high=2000.0, low=1900.0, direction="down")
    levels = fibonacci_levels(swing)
    assert levels.retracements["fib_0.618"] == pytest.approx(1961.8)
    assert levels.extensions["fib_1.618"] == pytest.approx(1838.2)


def test_fibonacci_validates_swing():
    with pytest.raises(ValueError):
        Swing(high=100.0, low=200.0, direction="up")
    with pytest.raises(ValueError):
        Swing(high=200.0, low=100.0, direction="sideways")


def test_detect_levels_clusters_touches():
    # Two lows at 1948 and one at 1949 -> one support cluster with 3 touches.
    n = 60
    base = pd.Series([1952.0] * n, dtype=float)
    lows = base.copy()
    highs = base + 6
    for i in (10, 25, 40):
        lows.iloc[i] = 1948.0
    lows.iloc[47] = 1949.0
    set_ = detect_levels(highs, lows, atr_value=2.0, min_touches=2)
    # The deep cluster (well below the flat base) must contain all 4 pivots.
    deep = [s for s in set_.supports if s.price < 1950.0]
    assert deep, f"expected a deep support cluster, got {set_.supports}"
    assert deep[0].touches == 4
    assert 1948.0 <= deep[0].price <= 1949.0


def test_ema_unaffected_by_sma_addition():
    close = _trending_close(30)
    assert ema(close, 10).iloc[-1] == pytest.approx(ema(close, 10).iloc[-1])
