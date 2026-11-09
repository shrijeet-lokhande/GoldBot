"""Oscillator indicators: MACD and Stochastic RSI."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from goldbot.indicators.trend import ema, rsi


@dataclass
class MACDResult:
    """MACD line, signal line and histogram series."""

    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series

    @property
    def last_macd(self) -> float | None:
        return _last_valid(self.macd)

    @property
    def last_signal(self) -> float | None:
        return _last_valid(self.signal)

    @property
    def last_histogram(self) -> float | None:
        return _last_valid(self.histogram)

    @property
    def crossover(self) -> str | None:
        """``bullish``/``bearish`` when the last two bars crossed, else None."""
        if len(self.histogram) < 2:
            return None
        prev, last = self.histogram.iloc[-2], self.histogram.iloc[-1]
        try:
            if pd.isna(prev) or pd.isna(last):
                return None
        except (TypeError, ValueError):
            return None
        if prev <= 0 < last:
            return "bullish"
        if prev >= 0 > last:
            return "bearish"
        return None


def _last_valid(series: pd.Series) -> float | None:
    if len(series) == 0:
        return None
    val = series.iloc[-1]
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        return None
    return float(val)


def macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """Moving Average Convergence Divergence.

    MACD = EMA(fast) - EMA(slow); signal = EMA(signal_period) of MACD;
    histogram = MACD - signal.
    """
    if fast_period >= slow_period:
        raise ValueError("fast_period must be < slow_period")
    fast = ema(series, fast_period)
    slow = ema(series, slow_period)
    macd_line = fast - slow
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)


def stochastic_rsi(
    series: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Stochastic RSI: returns (%K, %D) series in [0, 100].

    %K = 100 * (RSI - min(RSI, stoch)) / (max(RSI, stoch) - min(RSI, stoch)),
    smoothed by ``k_smooth``; %D is the SMA of %K over ``d_smooth``.
    """
    if min(rsi_period, stoch_period, k_smooth, d_smooth) < 1:
        raise ValueError("all periods must be >= 1")
    rsi_vals = rsi(series, rsi_period)
    rsi_min = rsi_vals.rolling(stoch_period, min_periods=stoch_period).min()
    rsi_max = rsi_vals.rolling(stoch_period, min_periods=stoch_period).max()
    denom = (rsi_max - rsi_min).replace(0.0, float("nan"))
    raw_k = 100.0 * (rsi_vals - rsi_min) / denom
    k = raw_k.rolling(k_smooth, min_periods=1).mean()
    d = k.rolling(d_smooth, min_periods=1).mean()
    return k, d
