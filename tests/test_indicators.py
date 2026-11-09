"""Indicator correctness tests (EMA, RSI, ATR, ADX)."""

import numpy as np
import pandas as pd
import pytest

from goldbot.indicators import adx, atr, ema, rsi


def test_ema_constant_series_equals_input():
    series = pd.Series([100.0] * 50)
    result = ema(series, 20)
    assert np.allclose(result, 100.0)


def test_ema_linear_ramp_has_expected_warmup():
    series = pd.Series([float(x) for x in range(1, 301)])
    result = ema(series, 10)
    assert len(result) == 300
    # EMA of a ramp must sit below the latest price
    assert result.iloc[-1] < series.iloc[-1]
    assert result.iloc[-1] > series.iloc[-10]


def test_ema_period_validation():
    with pytest.raises(ValueError):
        ema(pd.Series([1.0, 2.0]), 0)


def test_rsi_bounds():
    rng = np.random.default_rng(42)
    series = pd.Series(100 + np.cumsum(rng.normal(0, 1, 500)))
    result = rsi(series, 14).dropna()
    assert ((result >= 0) & (result <= 100)).all()


def test_rsi_all_gains_is_100():
    series = pd.Series([float(x) for x in range(1, 100)])
    result = rsi(series, 14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_0():
    series = pd.Series([float(-x) for x in range(1, 100)])
    result = rsi(series, 14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_period_validation():
    with pytest.raises(ValueError):
        rsi(pd.Series([1.0, 2.0, 3.0]), 0)


def test_atr_constant_candles():
    n = 30
    high = pd.Series([101.0] * n)
    low = pd.Series([99.0] * n)
    close = pd.Series([100.0] * n)
    result = atr(high, low, close, 14)
    assert result.iloc[-1] == pytest.approx(2.0)


def test_atr_gap_move_increases_true_range():
    n = 40
    high = pd.Series([101.0] * n)
    low = pd.Series([99.0] * n)
    close = pd.Series([100.0] * n)
    close.loc[39] = 120.0  # big jump on the final close
    high.loc[39] = 121.0
    low.loc[39] = 99.0
    result = atr(high, low, close, 14)
    prior = atr(
        high.iloc[:-1].reset_index(drop=True),
        low.iloc[:-1].reset_index(drop=True),
        close.iloc[:-1].reset_index(drop=True),
        14,
    )
    assert result.iloc[-1] > prior.iloc[-1]


def test_atr_period_validation():
    with pytest.raises(ValueError):
        atr(pd.Series([1.0] * 5), pd.Series([2.0] * 5), pd.Series([1.5] * 5), 0)


def test_adx_ranges_and_strong_uptrend():
    # A strongly trending series: monotonic rise with equal steps
    n = 300
    base = np.linspace(100.0, 130.0, n)
    high = pd.Series(base + 0.5)
    low = pd.Series(base - 0.5)
    close = pd.Series(base)
    result = adx(high, low, close, 14).dropna()
    assert len(result) > 0
    assert ((result >= 0) & (result <= 100)).all()
    # an uninterrupted rise is a strong trend: ADX must reach strong territory
    assert result.iloc[-40:].max() > 25


def test_adx_choppy_series_is_weak():
    # Deterministically alternating series: +DM and -DM are balanced,
    # so directional strength must stay low.
    n = 300
    steps = np.array([1.0, -1.0] * (n // 2))
    mid = 100.0 + np.cumsum(steps)
    high = pd.Series(mid + 0.6)
    low = pd.Series(mid - 0.6)
    close = pd.Series(mid)
    result = adx(high, low, close, 14).dropna()
    assert len(result) > 0
    assert result.iloc[-1] < 25


def test_adx_period_validation():
    with pytest.raises(ValueError):
        adx(pd.Series([1.0] * 5), pd.Series([2.0] * 5), pd.Series([1.5] * 5), 0)
