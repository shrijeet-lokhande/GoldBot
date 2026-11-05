"""GoldBot ADX (Average Directional Index) trend-strength indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from goldbot.core.models import IndicatorResult  # noqa: F401


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Average Directional Index (Wilder's method).

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        period: ADX lookback period.

    Returns:
        ADX series in [0, 100]. Values > 25 indicate strong trend; < 20
        indicate weak/ranging market. Early values may be NaN until warmed up.
    """
    if period < 1:
        raise ValueError("ADX period must be >= 1")

    high = high.reset_index(drop=True)
    low = low.reset_index(drop=True)
    close = close.reset_index(drop=True)

    # Wilder's directional movement:
    #   UpMove   = high - prev_high
    #   DownMove = prev_low - low
    #   +DM = UpMove   if UpMove > DownMove and UpMove > 0 else 0
    #   -DM = DownMove if DownMove > UpMove and DownMove > 0 else 0
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0).fillna(0.0)

    # True Range (first row falls back to the high-low range convention)
    prev_close = close.shift(1)
    tr_parts = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    tr = tr_parts.max(axis=1).fillna(high - low)

    # Wilder smoothing (RMA, alpha = 1/period).
    smoothing = dict(alpha=1.0 / period, adjust=False, min_periods=1)
    tr_smooth = tr.ewm(**smoothing).mean()
    plus_dm_smooth = plus_dm.ewm(**smoothing).mean()
    minus_dm_smooth = minus_dm.ewm(**smoothing).mean()

    # Directional Indicators
    safe_tr = tr_smooth.replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm_smooth / safe_tr
    minus_di = 100.0 * minus_dm_smooth / safe_tr

    # DX then smoothed ADX; flat markets (no DM) contribute DX = 0
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (100.0 * (plus_di - minus_di).abs() / denom).fillna(0.0)
    adx_val = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx_val
