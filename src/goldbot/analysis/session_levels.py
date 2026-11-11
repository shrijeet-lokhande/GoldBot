"""Session and reference levels for XAUUSD.

Gold's liquidity concentrates in specific sessions, making session extremes
and prior-period highs/lows primary reference levels for structure analysis:

- Asia (00:00-07:00 UTC): thin, range-bound; its high/low is a classic sweep
  target before the London open.
- London (07:00-12:00 UTC): first major liquidity window; often sets the
  intraday direction.
- New York (12:00-20:00 UTC): US data releases (8:30/10:00 ET) hit here; the
  London-NY overlap (12:00-16:00) is the deepest-liquidity window.
- Previous-day high/low (PDH/PDL) and previous-week high/low (PWH/PWL) are
  the most-watched liquidity pools; stop orders cluster above/below them.

These levels are *observed price extremes*, not fitted thresholds, so they
carry no arbitrary numeric constants. Session boundaries are fixed UTC hours
(banked liquidity follows the sun; DST shifts affect local clocks, not the
UTC ordering used by global FX desks).

Only completed candles are consumed; the current, still-forming candle is
excluded so no look-ahead is possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from goldbot.core.models import Candle

# Session windows in UTC hours [start, end) — rationale above.
SESSIONS_UTC: dict[str, tuple[int, int]] = {
    "asia": (0, 7),
    "london": (7, 12),
    "new_york": (12, 20),
}

DAY_MINUTES = 1440
WEEK_MINUTES = 10080


@dataclass(frozen=True)
class PeriodLevel:
    """High/low of a named session or prior period."""

    name: str
    high: float
    low: float
    start_utc: str
    end_utc: str
    candles: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "candles": self.candles,
        }


def _completed(candles: list[Candle]) -> list[Candle]:
    return [c for c in candles if c.is_complete]


def _session_levels(
    candles: list[Candle],
    name: str,
    window: tuple[int, int],
    day_start: datetime,
) -> PeriodLevel | None:
    start_hour, end_hour = window
    selected = [
        c for c in candles
        if start_hour <= c.timestamp_utc.astimezone(timezone.utc).hour < end_hour
        and c.timestamp_utc.astimezone(timezone.utc).date() == day_start.date()
    ]
    if not selected:
        return None
    return PeriodLevel(
        name=name,
        high=max(c.high for c in selected),
        low=min(c.low for c in selected),
        start_utc=day_start.replace(hour=start_hour).isoformat(),
        end_utc=day_start.replace(hour=end_hour - 1).isoformat(),
        candles=len(selected),
    )


def session_levels(
    candles: list[Candle],
    reference_day: datetime | None = None,
) -> dict[str, PeriodLevel]:
    """Session high/low for the requested day (default: latest completed day)."""
    candles = _completed(candles)
    if not candles:
        return {}
    if reference_day is None:
        reference_day = candles[-1].timestamp_utc.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        reference_day = reference_day.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    out: dict[str, PeriodLevel] = {}
    for name, window in SESSIONS_UTC.items():
        level = _session_levels(candles, name, window, reference_day)
        if level is not None:
            out[name] = level
    return out


def previous_day_high_low(candles: list[Candle]) -> PeriodLevel | None:
    """PDH/PDL: extremes of the last fully completed UTC day.

    Rule: take the most recent candle's day D, then compute the range of all
    completed candles strictly before D. If no earlier candles exist, None.
    """
    candles = _completed(candles)
    if not candles:
        return None
    current_day = candles[-1].timestamp_utc.astimezone(timezone.utc).date()
    prior = [
        c for c in candles
        if c.timestamp_utc.astimezone(timezone.utc).date() < current_day
    ]
    if not prior:
        return None
    last = prior[-1].timestamp_utc.astimezone(timezone.utc)
    day_start = last.replace(hour=0, minute=0, second=0, microsecond=0)
    same_day = [
        c for c in prior
        if c.timestamp_utc.astimezone(timezone.utc).date() == day_start.date()
    ]
    if not same_day:
        return None
    return PeriodLevel(
        name="previous_day",
        high=max(c.high for c in same_day),
        low=min(c.low for c in same_day),
        start_utc=day_start.isoformat(),
        end_utc=same_day[-1].timestamp_utc.isoformat(),
        candles=len(same_day),
    )


def previous_week_high_low(candles: list[Candle]) -> PeriodLevel | None:
    """PWH/PWL: extremes of the last fully completed ISO week (Mon-Sun UTC).

    Rule: take the most recent candle's ISO week W, then compute the range of
    all completed candles in strictly earlier ISO weeks.
    """
    candles = _completed(candles)
    if not candles:
        return None
    current = candles[-1].timestamp_utc.astimezone(timezone.utc)
    current_year, current_week, _ = current.isocalendar()
    prior = [
        c for c in candles
        if c.timestamp_utc.astimezone(timezone.utc).isocalendar()[:2]
        < (current_year, current_week)
    ]
    if not prior:
        return None
    last = prior[-1].timestamp_utc.astimezone(timezone.utc)
    wy, wk, _ = last.isocalendar()
    monday = datetime.fromisocalendar(wy, wk, 1).replace(tzinfo=timezone.utc)
    same_week = [
        c for c in prior
        if c.timestamp_utc.astimezone(timezone.utc).isocalendar()[:2] == (wy, wk)
    ]
    if not same_week:
        return None
    return PeriodLevel(
        name="previous_week",
        high=max(c.high for c in same_week),
        low=min(c.low for c in same_week),
        start_utc=monday.isoformat(),
        end_utc=same_week[-1].timestamp_utc.isoformat(),
        candles=len(same_week),
    )


def reference_levels(candles: list[Candle]) -> dict:
    """All watch-list reference levels for the analysis report.

    Returns a dict with per-day session extremes plus PDH/PDL and PWH/PWL,
    each with its observation window so staleness is auditable.
    """
    out: dict[str, object] = {}
    for name, level in session_levels(candles).items():
        out[f"session_{name}"] = level.to_dict()
    pd = previous_day_high_low(candles)
    if pd is not None:
        out["previous_day"] = pd.to_dict()
    pw = previous_week_high_low(candles)
    if pw is not None:
        out["previous_week"] = pw.to_dict()
    out["sessions_utc"] = {
        name: f"{s:02d}:00-{e:02d}:00" for name, (s, e) in SESSIONS_UTC.items()
    }
    return out


__all__ = [
    "SESSIONS_UTC",
    "PeriodLevel",
    "session_levels",
    "previous_day_high_low",
    "previous_week_high_low",
    "reference_levels",
]
