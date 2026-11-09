"""Multi-timeframe candle resampling with UTC alignment.

Resamples a base-timeframe candle list into higher timeframes. Timestamps are
bucketed on exact UTC boundaries (minutes are whole divisors of the hour/day),
so candles from any source are aligned consistently.

Lower timeframes than the base (e.g. 1m/5m from 15m data) cannot be derived;
``resample_candles`` raises in that case and callers must mark those
timeframes unavailable rather than approximating them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from goldbot.core.models import Candle

# Supported analysis timeframes in minutes (1w handled specially).
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}

ANALYSIS_TIMEFRAMES = tuple(TIMEFRAME_MINUTES)


def timeframe_minutes(timeframe: str) -> int:
    try:
        return TIMEFRAME_MINUTES[timeframe]
    except KeyError:
        raise ValueError(f"unsupported timeframe {timeframe!r}") from None


def bucket_start(ts: datetime, minutes: int) -> datetime:
    """UTC-aligned bucket start for a timestamp (weekly buckets start Monday)."""
    ts = ts.astimezone(timezone.utc)
    if minutes >= 10080:  # weekly: align to Monday 00:00 UTC
        monday = ts - timedelta(days=ts.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    if minutes >= 1440:  # daily
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    epoch_minutes = (ts.hour * 60 + ts.minute) // minutes * minutes
    return ts.replace(
        hour=epoch_minutes // 60,
        minute=epoch_minutes % 60,
        second=0,
        microsecond=0,
    )


def resample_candles(
    candles: list[Candle],
    timeframe: str,
) -> list[Candle]:
    """Aggregate base candles into ``timeframe`` buckets (UTC-aligned).

    Raises ValueError when the requested timeframe is finer than the source
    data (deriving lower timeframes is impossible without native data).
    """
    minutes = timeframe_minutes(timeframe)
    if not candles:
        return []
    base_minutes = TIMEFRAME_MINUTES.get(candles[0].timeframe)
    if base_minutes is None:
        # Unknown base timeframe: derive it from the first two timestamps.
        if len(candles) >= 2:
            delta = (candles[1].timestamp_utc - candles[0].timestamp_utc).total_seconds() / 60.0
            base_minutes = int(delta) if delta > 0 else None
    if base_minutes is not None and minutes < base_minutes:
        raise ValueError(
            f"cannot derive {timeframe} from {candles[0].timeframe} data; "
            "native lower-timeframe data required"
        )

    out: list[Candle] = []
    bucket_ts: datetime | None = None
    group: list[Candle] = []
    for candle in candles:
        start = bucket_start(candle.timestamp_utc, minutes)
        if bucket_ts is None or start != bucket_ts:
            if group:
                out.append(_merge(group, timeframe))
            bucket_ts = start
            group = [candle]
        else:
            group.append(candle)
    if group:
        out.append(_merge(group, timeframe))
    return out


def _merge(group: list[Candle], timeframe: str) -> Candle:
    first, last = group[0], group[-1]
    return Candle(
        symbol=first.symbol,
        timeframe=timeframe,
        timestamp_utc=bucket_start(first.timestamp_utc, timeframe_minutes(timeframe)),
        open=first.open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=last.close,
        volume=sum(c.volume for c in group),
        bid=last.bid,
        ask=last.ask,
        source=first.source,
        is_complete=last.is_complete,
    )
