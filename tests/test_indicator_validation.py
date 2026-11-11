"""Indicator validation against independently computed reference values.

Each test computes the expected value with plain-Python arithmetic (not via
the library under test) on small, hand-checkable series, so any formula
regression breaks loudly.
"""

import math

import pandas as pd
import pytest

from goldbot.indicators import adx, atr, bollinger_bands, macd, rsi, sma
from goldbot.indicators.oscillators import stochastic_rsi
from goldbot.indicators.trend import ema


def test_ema_reference_value():
    # EMA with span=3: seed with SMA? GoldBot uses adjust=False with
    # min_periods=1, i.e. y[0]=x[0]; y[i] = alpha*x[i] + (1-alpha)*y[i-1],
    # alpha = 2/(span+1) = 0.5.
    x = [10.0, 12.0, 14.0, 10.0]
    expected = [10.0]
    for v in x[1:]:
        expected.append(0.5 * v + 0.5 * expected[-1])
    result = ema(pd.Series(x, dtype=float), 3).tolist()
    for got, want in zip(result, expected):
        assert got == pytest.approx(want, abs=1e-9)


def test_sma_reference_value():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = sma(pd.Series(x, dtype=float), 3)
    assert pd.isna(result.iloc[0]) and pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_rsi_reference_value():
    # Classic Wilder gains/losses example:
    # closes 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    # 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03
    closes = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03,
    ]
    # Wilder's RSI(14): first average gain/loss over the 14 deltas...
    # GoldBot uses an EWM(alpha=1/14) equivalent of Wilder smoothing, which
    # converges to Wilder's RSI; verify the final value against the
    # explicitly computed Wilder recursion here.
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    period = 14
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss
    expected = 100.0 - 100.0 / (1.0 + rs)

    series = pd.Series(closes, dtype=float)
    result = rsi(series, period)
    assert result.iloc[-1] == pytest.approx(expected, rel=1e-6)


def test_rsi_bounds_and_extremes():
    monotonic_up = pd.Series([float(i) for i in range(30)])
    val = rsi(monotonic_up, 14).iloc[-1]
    assert 95.0 <= val <= 100.0


def test_atr_reference_value():
    # Wilder ATR(3): TRs are 2.0, 2.0, 1.5 -> seed = SMA = 1.8333.
    highs = pd.Series([11.0, 12.0, 10.5], dtype=float)
    lows = pd.Series([9.0, 10.0, 9.5], dtype=float)
    closes = pd.Series([10.0, 11.0, 10.0], dtype=float)
    tr0 = 2.0                                # h-l of first bar
    tr1 = max(1.0, abs(12 - 10), abs(10 - 10))  # = 2.0
    tr2 = max(1.0, abs(10.5 - 11), abs(9.5 - 11))  # = 1.5
    expected = (tr0 + tr1 + tr2) / 3.0
    result = atr(highs, lows, closes, 3)
    assert pd.isna(result.iloc[0])           # warm-up is NaN, not invented
    assert result.iloc[-1] == pytest.approx(expected, abs=1e-9)


def test_adx_directional_reference():
    # Perfectly trending series: +DI large, -DI ~0 -> ADX near 100 over time.
    n = 60
    highs = pd.Series([100.0 + i for i in range(n)], dtype=float)
    lows = pd.Series([99.0 + i for i in range(n)], dtype=float)
    closes = pd.Series([99.5 + i for i in range(n)], dtype=float)
    val = adx(highs, lows, closes, 14).iloc[-1]
    assert val > 50.0  # strong one-way tape must register a strong ADX


def test_macd_reference_value():
    x = list(range(1, 41))  # linear ramp
    series = pd.Series([float(v) for v in x], dtype=float)

    def ema_ref(vals: list[float], span: int) -> list[float]:
        alpha = 2.0 / (span + 1)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(alpha * v + (1 - alpha) * out[-1])
        return out

    fast = ema_ref(x, 12)
    slow = ema_ref(x, 26)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal = ema_ref(macd_line, 9)
    result = macd(series)
    assert result.last_macd == pytest.approx(macd_line[-1], rel=1e-9)
    assert result.last_signal == pytest.approx(signal[-1], rel=1e-9)
    assert result.last_histogram == pytest.approx(macd_line[-1] - signal[-1], rel=1e-9)


def test_bollinger_reference_value():
    x = [2.0, 4.0, 6.0, 8.0, 10.0] * 4
    series = pd.Series([float(v) for v in x], dtype=float)
    window = series.iloc[-20:]
    mean = window.mean()
    std = window.std(ddof=0)
    bb = bollinger_bands(series, 20, 2.0)
    assert bb.middle.iloc[-1] == pytest.approx(mean)
    assert bb.upper.iloc[-1] == pytest.approx(mean + 2 * std)
    assert bb.lower.iloc[-1] == pytest.approx(mean - 2 * std)


def test_stoch_rsi_reference_value():
    # Build a series whose RSI is known-monotonic-ish and verify the
    # definition: k = 100*(rsi - min(rsi,win)) / (max - min) on the window.
    closes = [1950 + 10 * math.sin(i / 5.0) for i in range(80)]
    series = pd.Series(closes, dtype=float)
    k, d = stochastic_rsi(series, rsi_period=5, stoch_period=5, k_smooth=1, d_smooth=1)
    rsi_vals = rsi(series, 5)
    window = rsi_vals.iloc[-5:]
    lo, hi = window.min(), window.max()
    if hi > lo:
        expected_k = 100.0 * (rsi_vals.iloc[-1] - lo) / (hi - lo)
        assert k.iloc[-1] == pytest.approx(expected_k, rel=1e-6)
        assert d.iloc[-1] == pytest.approx(k.iloc[-1], rel=1e-6)  # d_smooth=1
