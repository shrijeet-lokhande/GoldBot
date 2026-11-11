"""Shared Wilder smoothing primitives (exact textbook recursion)."""

from __future__ import annotations

import numpy as np


def wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (RMA): SMA seed, then (prev*(p-1) + x)/p.

    Returns an array of the same length; positions before the seed
    (index < period-1) are NaN so consumers never read a warm-up value.
    """
    out = np.full(values.shape[0], np.nan)
    if values.shape[0] < period or period < 1:
        return out
    out[period - 1] = float(np.mean(values[:period]))
    alpha = 1.0 / period
    for i in range(period, values.shape[0]):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


__all__ = ["wilder_smooth"]
