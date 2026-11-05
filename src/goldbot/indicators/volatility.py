"""GoldBot volatility indicator - Average True Range (ATR)."""

from __future__ import annotations

import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Average True Range (14-period default).

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series (previous close for the first TR).
        period: ATR lookback period.

    Returns:
        ATR series. NaN for the first `period` values.
    """
    if period < 1:
        raise ValueError("ATR period must be >= 1")

    # True Range: max(high-low, abs(high-previous_close), abs(low-previous_close))
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # EMA of True Range
    return tr.ewm(span=period, adjust=False, min_periods=1).mean()
