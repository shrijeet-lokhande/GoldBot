"""GoldBot volatility indicator — Average True Range (Wilder's method)."""

from __future__ import annotations

import pandas as pd

from goldbot.indicators.wilder import wilder_smooth


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range — canonical Wilder smoothing (alpha = 1/period).

    True Range: max(high-low, |high-prev_close|, |low-prev_close|); the first
    TR falls back to high-low (no previous close exists). The seed is the SMA
    of the first ``period`` TRs, then Wilder recursion thereafter. Values
    before the warm-up are NaN, so callers never consume a not-yet-valid ATR.
    """
    if period < 1:
        raise ValueError("ATR period must be >= 1")

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    tr = tr.fillna(tr1)  # first bar has no previous close

    tr_values = tr.to_numpy(dtype=float)
    smoothed = wilder_smooth(tr_values, period)
    return pd.Series(smoothed, index=close.index)
