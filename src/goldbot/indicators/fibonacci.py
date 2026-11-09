"""Fibonacci retracement and extension levels.

Measured from an explicit swing (high, low, direction) so levels are always
traceable to concrete price points — never fitted ambiguously.
"""

from __future__ import annotations

from dataclasses import dataclass

RETRACEMENT_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSION_RATIOS = (1.0, 1.272, 1.618, 2.0, 2.618)


@dataclass(frozen=True)
class Swing:
    """A completed swing leg used as the basis for Fib levels."""

    high: float
    low: float
    direction: str  # "up" (low->high impulse) or "down" (high->low impulse)

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'")
        if self.high < self.low:
            raise ValueError("swing high must be >= swing low")


@dataclass(frozen=True)
class FibLevels:
    """Fibonacci retracement and extension price levels."""

    direction: str
    retracements: dict[str, float]
    extensions: dict[str, float]


def fibonacci_levels(swing: Swing) -> FibLevels:
    """Compute retracement and extension levels for a swing.

    For an ``up`` swing (low -> high):
      retracements pull back below the high: high - ratio * (high - low);
      extensions project above the high: high + (ratio - 1) * range, i.e.
      level = low + ratio * range for ratio >= 1.
    For a ``down`` swing the mirror applies.
    """
    rng = swing.high - swing.low
    retracements: dict[str, float] = {}
    extensions: dict[str, float] = {}
    if swing.direction == "up":
        for r in RETRACEMENT_RATIOS:
            retracements[f"fib_{r}"] = round(swing.high - r * rng, 6)
        for r in EXTENSION_RATIOS:
            extensions[f"fib_{r}"] = round(swing.low + r * rng, 6)
    else:
        for r in RETRACEMENT_RATIOS:
            retracements[f"fib_{r}"] = round(swing.low + r * rng, 6)
        for r in EXTENSION_RATIOS:
            extensions[f"fib_{r}"] = round(swing.high - r * rng, 6)
    return FibLevels(
        direction=swing.direction,
        retracements=retracements,
        extensions=extensions,
    )
