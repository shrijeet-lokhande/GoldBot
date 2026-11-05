"""GoldBot market data normalizer - standardizes candle and quote fields."""

from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone
from typing import Any, Optional

from goldbot.core.models import Candle, Quote


def normalize_candle(candle: dict[str, Any]) -> Candle:
    """Normalize a raw candle dict into a domain Candle model.

    Ensures:
        - Timestamps are UTC datetime objects
        - Numeric fields are float
        - Candle invariants are checked:
          high >= max(open, close), low <= min(open, close), high >= low
        - Missing bid/ask are set to None

    Args:
        candle: Raw dict with candle fields.

    Returns:
        A normalized Candle instance.

    Raises:
        ValueError: If the candle data fails validation.
    """
    ts = candle.get("timestamp")
    if ts is None:
        raise ValueError("Candle missing 'timestamp'")

    # Convert timestamp to UTC datetime
    if isinstance(ts, str):
        dt_obj = _parse_iso_timestamp(ts)
    elif isinstance(ts, datetime):
        dt_obj = ts if ts.tzinfo else datetime(ts.year, ts.month, ts.day, tzinfo=None)
    elif isinstance(ts, (int, float)):
        dt_obj = datetime.fromtimestamp(ts, tz=None)  # naive, will be treated as UTC
    else:
        raise ValueError(f"Unsupported timestamp type: {type(ts)}")

    # Ensure UTC
    if dt_obj.tzinfo is not None:
        dt_obj = dt_obj.astimezone(timezone.utc)  # type: ignore[arg-type]
    else:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)  # type: ignore[attr-defined]

    open_price = float(candle.get("open", 0))
    high_price = float(candle.get("high", 0))
    low_price = float(candle.get("low", 0))
    close_price = float(candle.get("close", 0))
    volume = float(candle.get("volume", 0))

    bid: Optional[float] = candle.get("bid")
    if bid is not None:
        bid = float(bid)
    ask: Optional[float] = candle.get("ask")
    if ask is not None:
        ask = float(ask)

    is_complete = candle.get("is_complete", True)
    if not isinstance(is_complete, bool):
        is_complete = bool(is_complete)

    source = candle.get("source", "unknown")

    # Validate invariants
    if not (high_price >= max(open_price, close_price)):
        raise ValueError(
            f"Candle invariant violated: high {high_price} < "
            f"max(open {open_price}, close {close_price})"
        )
    if not (low_price <= min(open_price, close_price)):
        raise ValueError(
            f"Candle invariant violated: low {low_price} > "
            f"min(open {open_price}, close {close_price})"
        )
    if not (high_price >= low_price):
        raise ValueError(f"Candle invariant violated: high {high_price} < low {low_price}")

    return Candle(
        symbol=candle.get("symbol", ""),
        timeframe=candle.get("timeframe", ""),
        timestamp_utc=dt_obj,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        bid=bid,
        ask=ask,
        source=source,
        is_complete=is_complete,
    )


def normalize_quote(quote: dict[str, Any]) -> Quote | None:
    """Normalize a raw quote dict into a domain Quote model.

    Returns None if bid or ask is missing or invalid.
    """
    bid = quote.get("bid")
    ask = quote.get("ask")
    if bid is None or ask is None:
        return None
    try:
        bid = float(bid)
        ask = float(ask)
    except (ValueError, TypeError):
        return None
    return Quote(
        bid=bid,
        ask=ask,
        timestamp=datetime.now(timezone.utc),
    )


def _parse_iso_timestamp(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware UTC datetime."""
    # Handle "Z" suffix
    normalized = ts.replace("Z", "+00:00")
    dt_obj = dt.datetime.fromisoformat(normalized)
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    else:
        dt_obj = dt_obj.astimezone(timezone.utc)
    return dt_obj
