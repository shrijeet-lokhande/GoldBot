"""Support and resistance level detection.

Levels are clustered swing pivots: a swing low touched by >= min_touches
within ``tolerance_atr`` ATRs of other lows is a support cluster; the mirror
holds for resistance. Every reported level carries its touch count and mean
price so downstream consumers can weigh and audit them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class PriceLevel:
    """A support or resistance cluster."""

    kind: str  # "support" | "resistance"
    price: float  # cluster mean
    touches: int  # number of pivots in the cluster
    last_touch_index: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "price": round(float(self.price), 4),
            "touches": self.touches,
            "last_touch_index": self.last_touch_index,
        }


@dataclass
class LevelSet:
    supports: list[PriceLevel] = field(default_factory=list)
    resistances: list[PriceLevel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "supports": [s.to_dict() for s in self.supports],
            "resistances": [r.to_dict() for r in self.resistances],
        }


def _pivot_indices(
    high: pd.Series, low: pd.Series, left: int, right: int
) -> tuple[list[int], list[int]]:
    """Indices of swing-high and swing-low pivots (fractal definition)."""
    highs, lows = [], []
    n = len(high)
    for i in range(left, n - right):
        window_h = high.iloc[i - left : i + right + 1]
        window_l = low.iloc[i - left : i + right + 1]
        if high.iloc[i] == window_h.max():
            highs.append(i)
        if low.iloc[i] == window_l.min():
            lows.append(i)
    return highs, lows


def detect_levels(
    high: pd.Series,
    low: pd.Series,
    atr_value: float | None = None,
    pivot_left: int = 3,
    pivot_right: int = 3,
    min_touches: int = 2,
    tolerance_atr: float = 0.5,
) -> LevelSet:
    """Cluster swing pivots into support/resistance levels.

    Tolerance: two pivots belong to the same cluster when within
    ``tolerance_atr`` * ATR (or 0.1% of mean price when ATR unavailable).
    Clusters with < min_touches pivots are discarded.
    """
    if len(high) == 0 or len(low) == 0:
        return LevelSet()
    high = high.reset_index(drop=True)
    low = low.reset_index(drop=True)

    tol = tolerance_atr * atr_value if atr_value and atr_value > 0 else None

    def _cluster(points: list[tuple[int, float]]) -> list[list[int]]:
        price_of = dict(points)
        clusters: list[list[int]] = []
        for i, price in points:
            local_tol = tol if tol is not None else price * 0.001
            placed = False
            for cluster in clusters:
                mean = sum(price_of[j] for j in cluster) / len(cluster)
                if abs(price - mean) <= local_tol:
                    cluster.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])
        return clusters

    high_idx, low_idx = _pivot_indices(high, low, pivot_left, pivot_right)
    out = LevelSet()

    for cluster in _cluster([(i, low.iloc[i]) for i in low_idx]):
        if len(cluster) >= min_touches:
            out.supports.append(
                PriceLevel(
                    kind="support",
                    price=sum(low.iloc[i] for i in cluster) / len(cluster),
                    touches=len(cluster),
                    last_touch_index=max(cluster),
                )
            )
    for cluster in _cluster([(i, high.iloc[i]) for i in high_idx]):
        if len(cluster) >= min_touches:
            out.resistances.append(
                PriceLevel(
                    kind="resistance",
                    price=sum(high.iloc[i] for i in cluster) / len(cluster),
                    touches=len(cluster),
                    last_touch_index=max(cluster),
                )
            )

    out.supports.sort(key=lambda s: -s.price)  # nearest-to-price first
    out.resistances.sort(key=lambda r: r.price)
    return out
