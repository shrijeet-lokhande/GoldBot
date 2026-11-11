"""RSI — canonical Wilder implementation (exact textbook recursion).

The first average gain/loss is an SMA over the first ``period`` deltas;
afterwards Wilder smoothing (alpha = 1/period). Values before the warm-up are
NaN (Wilder's RSI is undefined there), so callers never compute signals off a
not-yet-valid indicator. A perfectly flat series (no gains, no losses) is
neutral 50 by convention.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from goldbot.indicators.wilder import wilder_smooth


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index; NaN during warm-up, values in [0, 100]."""
    if period < 1:
        raise ValueError("RSI period must be >= 1")

    delta = series.diff()
    if len(delta) < period + 1:  # need `period` real deltas
        return pd.Series(np.nan, index=series.index)

    gains = delta.clip(lower=0).to_numpy(dtype=float)[1:]   # drop NaN delta[0]
    losses = (-delta.clip(upper=0)).to_numpy(dtype=float)[1:]

    avg_gain = wilder_smooth(gains, period)
    avg_loss = wilder_smooth(losses, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        values = 100.0 - (100.0 / (1.0 + rs))
    values = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, values)
    values = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, values)  # flat tape
    values = np.where((avg_gain == 0) & (avg_loss > 0), 0.0, values)

    result = pd.Series(np.nan, index=series.index)
    result.iloc[period:] = values[period - 1:]
    return result
