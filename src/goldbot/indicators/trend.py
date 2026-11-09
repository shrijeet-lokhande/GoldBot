"""GoldBot indicator engine - technical indicators for gold trading."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average.

    Returns NaN for the first ``period - 1`` values (a true rolling mean,
    unlike the EMA which is defined from the first bar).
    """
    if period < 1:
        raise ValueError("SMA period must be >= 1")
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average.

    Args:
        series: Price series (typically close prices).
        period: EMA period.

    Returns:
        EMA series with the same index as input. Will contain NaN for
        the first `period - 1` values until warmed up.
    """
    if period < 1:
        raise ValueError("EMA period must be >= 1")
    return series.ewm(span=period, adjust=False, min_periods=1).mean()


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

    # Wilder smoothing (RMA, alpha = 1/period)
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
