"""GoldBot momentum indicator - RSI calculation."""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (14-period default).

    Args:
        series: Price series (typically close prices).
        period: RSI lookback period.

    Returns:
        RSI series with values in [0, 100]. NaN for the first `period`
        values.
    """
    if period < 1:
        raise ValueError("RSI period must be >= 1")

    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    # Exponential moving average of up/down moves
    ma_up = up.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()

    rs = ma_up / ma_down
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val
