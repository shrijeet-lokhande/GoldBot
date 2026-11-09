"""Bollinger Bands."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BollingerResult:
    """Upper / middle / lower Bollinger Band series."""

    upper: pd.Series
    middle: pd.Series
    lower: pd.Series

    def percentile_b(self, close: float) -> float | None:
        """%B for a given close: 0 = at lower band, 1 = at upper band."""
        try:
            upper, lower = self.upper.iloc[-1], self.lower.iloc[-1]
        except IndexError:
            return None
        width = upper - lower
        if pd.isna(upper) or pd.isna(lower) or width == 0:
            return None
        return float((close - lower) / width)

    @property
    def bandwidth(self) -> float | None:
        """Latest bandwidth: (upper - lower) / middle * 100."""
        try:
            upper, middle, lower = (self.upper.iloc[-1], self.middle.iloc[-1], self.lower.iloc[-1])
        except IndexError:
            return None
        if pd.isna(middle) or middle == 0:
            return None
        return float((upper - lower) / middle * 100.0)


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerResult:
    """Classic Bollinger Bands: SMA(period) ± num_std * rolling std(ddof=0)."""
    if period < 2:
        raise ValueError("period must be >= 2")
    middle = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return BollingerResult(upper=upper, middle=middle, lower=lower)
