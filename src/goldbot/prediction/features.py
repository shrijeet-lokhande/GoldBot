"""Feature engineering for the XAUUSD prediction pipeline.

All features are computed ONLY from completed candles at time ``t`` and the
target is the sign of the forward return over the next ``horizon`` bars —
no look-ahead: feature row ``t`` uses data up to and including bar ``t``,
target row ``t`` uses bars ``t+1 .. t+horizon``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from goldbot.core.models import Candle
from goldbot.indicators import adx, atr, bollinger_bands, macd, rsi
from goldbot.indicators.trend import ema

FEATURE_NAMES = (
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "rsi_14",
    "atr_pct",
    "macd_hist_norm",
    "bb_pctb",
    "ema50_dist_atr",
    "session_asia",
    "session_london",
    "session_ny",
)


@dataclass(frozen=True)
class FeatureMatrix:
    names: tuple[str, ...]
    x: np.ndarray            # (rows, features)
    y: np.ndarray            # 1 = up over horizon, 0 = down
    forward_return: np.ndarray  # raw forward return (for MAE metrics)
    timestamps: list[str]    # ISO timestamp of the feature row
    horizon_bars: int


def _session_flags(ts: pd.Series) -> np.ndarray:
    hours = ts.dt.hour.to_numpy()
    asia = ((hours >= 0) & (hours < 7)).astype(float)
    london = ((hours >= 7) & (hours < 12)).astype(float)
    ny = ((hours >= 12) & (hours < 20)).astype(float)
    return np.column_stack([asia, london, ny])


def build_features(
    candles: list[Candle],
    horizon_bars: int = 4,
) -> FeatureMatrix:
    """Build the feature/target matrix from completed candles.

    ``horizon_bars`` default 4 = one hour on the 15m base timeframe.
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")

    completed = [c for c in candles if c.is_complete]
    if len(completed) < 60:
        raise ValueError(
            f"insufficient history for prediction: {len(completed)} completed "
            "bars (>= 60 required)"
        )

    close = pd.Series([c.close for c in completed], dtype=float)
    high = pd.Series([c.high for c in completed], dtype=float)
    low = pd.Series([c.low for c in completed], dtype=float)
    ts = pd.Series([c.timestamp_utc for c in completed])

    ret_1 = close.pct_change(1)
    ret_3 = close.pct_change(3)
    ret_5 = close.pct_change(5)
    ret_10 = close.pct_change(10)

    rsi_14 = rsi(close, 14) / 100.0                      # scale to [0, 1]
    atr_14 = atr(high, low, close, 14)
    atr_pct = atr_14 / close
    macd_res = macd(close)
    hist = pd.Series(macd_res.histogram, dtype=float)
    macd_hist_norm = hist / close
    bb = bollinger_bands(close, 20, 2.0)
    width = bb.upper - bb.lower
    bb_pctb = (close - bb.lower) / width.where(width > 0)
    ema_50 = ema(close, 50)
    ema50_dist_atr = (close - ema_50) / atr_14.where(atr_14 > 0)

    session = pd.DataFrame(_session_flags(ts), columns=["s_a", "s_l", "s_n"])

    frame = pd.concat(
        [
            ret_1.rename("ret_1"),
            ret_3.rename("ret_3"),
            ret_5.rename("ret_5"),
            ret_10.rename("ret_10"),
            rsi_14.rename("rsi_14"),
            atr_pct.rename("atr_pct"),
            macd_hist_norm.rename("macd_hist_norm"),
            bb_pctb.rename("bb_pctb"),
            ema50_dist_atr.rename("ema50_dist_atr"),
            session,
        ],
        axis=1,
    )

    # Forward return over the horizon (target side).
    fwd = close.shift(-horizon_bars) / close - 1.0

    # Drop warm-up rows (any feature NaN) and rows without a forward target.
    valid = frame.notna().all(axis=1) & fwd.notna()
    frame = frame.loc[valid]
    fwd = fwd.loc[valid]
    ts_valid = ts.loc[valid]

    x = frame.to_numpy(dtype=float)
    y = (fwd.to_numpy(dtype=float) > 0).astype(float)
    return FeatureMatrix(
        names=FEATURE_NAMES,
        x=x,
        y=y,
        forward_return=fwd.to_numpy(dtype=float),
        timestamps=[t.isoformat() for t in ts_valid],
        horizon_bars=horizon_bars,
    )


def latest_feature_row(candles: list[Candle], horizon_bars: int = 4) -> dict:
    """The feature vector for the most recent completed bar (live forecasting)."""
    completed = [c for c in candles if c.is_complete]
    if len(completed) < 60:
        raise ValueError("insufficient history for a live feature row")
    # build_features drops the last `horizon_bars` rows (no forward target);
    # recompute just the feature row for the final bar instead.
    # Reuse the same indicator pipeline on the full series:
    close = pd.Series([c.close for c in completed], dtype=float)
    high = pd.Series([c.high for c in completed], dtype=float)
    low = pd.Series([c.low for c in completed], dtype=float)
    ts = pd.Series([c.timestamp_utc for c in completed])

    rsi_14 = rsi(close, 14) / 100.0
    atr_14 = atr(high, low, close, 14)
    macd_res = macd(close)
    hist = pd.Series(macd_res.histogram, dtype=float)
    bb = bollinger_bands(close, 20, 2.0)
    width = bb.upper - bb.lower
    ema_50 = ema(close, 50)

    i = len(completed) - 1
    width_i = float(width.iloc[i])
    row = {
        "ret_1": float(close.iloc[i] / close.iloc[i - 1] - 1.0),
        "ret_3": float(close.iloc[i] / close.iloc[i - 3] - 1.0),
        "ret_5": float(close.iloc[i] / close.iloc[i - 5] - 1.0),
        "ret_10": float(close.iloc[i] / close.iloc[i - 10] - 1.0),
        "rsi_14": float(rsi_14.iloc[i]),
        "atr_pct": float(atr_14.iloc[i] / close.iloc[i]),
        "macd_hist_norm": float(hist.iloc[i] / close.iloc[i]),
        "bb_pctb": float((close.iloc[i] - bb.lower.iloc[i]) / width_i)
        if width_i > 0
        else 0.5,
        "ema50_dist_atr": float(
            (close.iloc[i] - ema_50.iloc[i]) / atr_14.iloc[i]
        )
        if float(atr_14.iloc[i]) > 0
        else 0.0,
        "session_asia": 1.0 if 0 <= ts.iloc[i].hour < 7 else 0.0,
        "session_london": 1.0 if 7 <= ts.iloc[i].hour < 12 else 0.0,
        "session_ny": 1.0 if 12 <= ts.iloc[i].hour < 20 else 0.0,
    }
    return row


def adx_regime(candles: list[Candle], period: int = 14) -> str:
    """Market regime from ADX (thresholds documented in docs/THRESHOLDS.md)."""
    completed = [c for c in candles if c.is_complete]
    high = pd.Series([c.high for c in completed], dtype=float)
    low = pd.Series([c.low for c in completed], dtype=float)
    close = pd.Series([c.close for c in completed], dtype=float)
    value = adx(high, low, close, period).iloc[-1]
    if np.isnan(value):
        return "unknown"
    if value >= 25.0:
        return "trending"
    if value < 20.0:
        return "range"
    return "transitional"


__all__ = [
    "FEATURE_NAMES",
    "FeatureMatrix",
    "build_features",
    "latest_feature_row",
    "adx_regime",
]
