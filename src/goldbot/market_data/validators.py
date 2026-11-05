"""GoldBot market data validators - validate candle integrity and quality."""

from __future__ import annotations

import datetime as dt

from goldbot.core.exceptions import DataError
from goldbot.core.models import Candle, DataQualityStatus


def validate_candle_integrity(candle: Candle) -> bool:
    """Validate the basic invariants of a candle.

    Checks:
        - high >= max(open, close)
        - low <= min(open, close)
        - high >= low

    Args:
        candle: The candle to validate.

    Returns:
        True if valid.

    Raises:
        DataError: If any invariant is violated.
    """
    if candle.high < max(candle.open, candle.close):
        raise DataError(
            f"Candle integrity violation: high {candle.high} < "
            f"max(open {candle.open}, close {candle.close})"
        )
    if candle.low > min(candle.open, candle.close):
        raise DataError(
            f"Candle integrity violation: low {candle.low} > "
            f"min(open {candle.open}, close {candle.close})"
        )
    if candle.high < candle.low:
        raise DataError(f"Candle integrity violation: high {candle.high} < low {candle.low}")
    return True


def check_data_quality(
    candle: Candle,
    stale_threshold_seconds: int = 120,
) -> dict[str, str]:
    """Assess the data quality of a candle.

    Args:
        candle: The candle to assess.
        stale_threshold_seconds: How many seconds ago data becomes "stale".

    Returns:
        A dict with quality status and reasons.
    """
    now = dt.datetime.now(dt.timezone.utc)
    age_seconds = (now - candle.timestamp_utc).total_seconds()

    reasons: list[str] = []
    status = DataQualityStatus.GOOD

    if age_seconds > stale_threshold_seconds:
        status = DataQualityStatus.STALE
        reasons.append(f"stale (age {age_seconds:.0f}s > {stale_threshold_seconds})")

    if candle.bid is None or candle.ask is None:
        reasons.append("missing bid/ask")
        if status == DataQualityStatus.GOOD:
            status = DataQualityStatus.MALFORMED

    if not candle.is_complete:
        reasons.append("incomplete candle")
        if status == DataQualityStatus.GOOD:
            status = DataQualityStatus.MALFORMED

    if candle.volume < 0:
        reasons.append("negative volume")
        if status == DataQualityStatus.GOOD:
            status = DataQualityStatus.MALFORMED

    return {
        "status": status,
        "age_seconds": f"{age_seconds:.0f}",
        "reasons": "; ".join(reasons) if reasons else "none",
    }


def ensure_completed(candle: Candle) -> Candle:
    """Ensure a candle is complete; raise if not.

    This is a safeguard for candle-close strategies that must only
    act after a candle has closed.

    Args:
        candle: The candle to check.

    Returns:
        The same candle if complete.

    Raises:
        DataError: If the candle is not complete.
    """
    if not candle.is_complete:
        raise DataError(
            f"Candle at {candle.timestamp_utc} is not complete; "
            "strategy requires completed candles only."
        )
    return candle
