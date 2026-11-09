"""VWAP (volume-weighted average price).

VWAP requires reliable volume data. GoldBot's candle replay dataset includes
volume, but when a feed reports zero/absent volume the calculation is
explicitly marked unavailable rather than silently producing a flat line.
"""

from __future__ import annotations

import pandas as pd


def has_reliable_volume(volume: pd.Series) -> bool:
    """True when the series exists, has positive length and any positive volume."""
    if volume is None or len(volume) == 0:
        return False
    return bool((volume.fillna(0) > 0).any())


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series | None:
    """Rolling VWAP over the whole provided window (session-less variant).

    Uses typical price (H+L+C)/3 weighted by volume. Returns None when volume
    is not reliable — callers must treat VWAP as unavailable, not zero.
    """
    if not has_reliable_volume(volume):
        return None
    typical = (high + low + close) / 3.0
    vol = volume.fillna(0.0)
    cum_pv = (typical * vol).cumsum()
    cum_v = vol.cumsum().replace(0.0, pd.NA)
    result = (cum_pv / cum_v).astype(float)
    return result
