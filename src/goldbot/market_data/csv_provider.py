"""GoldBot CSV market data provider for historical candles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from goldbot.core.exceptions import DataError
from goldbot.core.models import Candle, InstrumentMetadata, Quote
from goldbot.market_data.base import MarketDataProviderProtocol

logger = logging.getLogger("goldbot.market_data.csv")


class CsvMarketDataProvider(MarketDataProviderProtocol):
    """Load historical OHLCV candles from CSV files.

    Expected CSV column names (case-insensitive):
        timestamp, open, high, low, close, volume

    Additional optional columns:
        bid, ask, source, is_complete

    The provider normalizes timestamps to UTC and validates candle
    integrity. Malformed or out-of-order records are rejected with
    descriptive errors.
    """

    def __init__(self, csv_path: str | Path | None = None):
        self.csv_path = Path(csv_path) if csv_path else None
        self._cache: dict[tuple[str, str], list[Candle]] = {}

    def set_csv_path(self, csv_path: str | Path) -> None:
        """Set the CSV data path and clear cache."""
        self.csv_path = Path(csv_path)
        self._cache.clear()
        logger.info("CSV data path set to %s", self.csv_path)

    # ---- Protocol implementations ----

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Load candles from CSV within the given date range.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe (e.g. "15m").
            start: Start datetime inclusive (UTC).
            end: End datetime inclusive (UTC).

        Returns:
            List of Candle objects normalized to UTC.
        """
        cache_key = (symbol, timeframe)
        if cache_key in self._cache:
            candles = self._cache[cache_key]
        else:
            candles = self._load_all_candles(symbol, timeframe)
            # Filter to date range
            candles = [
                c for c in candles
                if start <= c.timestamp_utc <= end
            ]
            # Sort ascending by timestamp
            candles.sort(key=lambda c: c.timestamp_utc)
            self._cache[cache_key] = candles

        logger.debug(
            "Loaded %d bars for %s %s in range %s-%s",
            len(candles), symbol, timeframe, start, end,
        )
        return candles

    def get_latest_bar(self, symbol: str, timeframe: str) -> Optional[Candle]:
        """Get the latest completed bar from CSV data.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.

        Returns:
            The most recent completed Candle, or None if no data.
        """
        candles = self.get_historical_bars(symbol, timeframe, datetime.min, datetime.now())
        if not candles:
            return None
        # Return the last (most recent) completed candle
        return candles[-1]

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """CSV providers typically don't supply bid/ask.

        Returns None to indicate that bid/ask is not available from this
        source. The strategy or risk engine must handle this case.
        """
        return None

    def get_instrument_metadata(self, symbol: str) -> InstrumentMetadata:
        """Return basic metadata; CSV provider has no verified specs.

        Callers must validate metadata before using it for sizing or
        risk calculations. If metadata is required and unverified, the
        trade should be rejected.
        """
        from goldbot.core.models import InstrumentMetadata

        return InstrumentMetadata(
            symbol=symbol,
            contract_size=None,
            tick_size=None,
            tick_value=None,
            volume_step=None,
            min_volume=None,
            trading_hours=None,
            margin_rate=None,
            commission=None,
            swap_long=None,
            swap_short=None,
            verified=False,
            source="csv_unverified",
        )

    # ---- Internal CSV loading ----

    def _load_all_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        """Load all candles from CSV, with normalization and validation.

        Raises:
            DataError: If the CSV is missing, malformed, or contains
                invalid candle data.
        """
        if not self.csv_path or not self.csv_path.exists():
            msg = f"CSV file not found: {self.csv_path}"
            raise DataError(msg)

        try:
            df = pd.read_csv(self.csv_path)
        except Exception as exc:
            msg = f"Failed to read CSV {self.csv_path}: {exc}"
            raise DataError(msg) from exc

        if df.empty:
            msg = f"CSV file is empty: {self.csv_path}"
            raise DataError(msg)

        # Normalize column names to lowercase
        df.columns = [c.strip().lower() for c in df.columns]
        logger.debug("CSV columns: %s", list(df.columns))

        # Required columns
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            msg = f"CSV missing required columns: {sorted(missing)}"
            raise DataError(msg)

        # Parse timestamps - expect ISO format or Unix timestamp
        timestamps = self._parse_timestamps(df["timestamp"])
        opens = pd.to_numeric(df["open"], errors="coerce")
        highs = pd.to_numeric(df["high"], errors="coerce")
        lows = pd.to_numeric(df["low"], errors="coerce")
        closes = pd.to_numeric(df["close"], errors="coerce")
        if "volume" in df.columns:
            volumes = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        else:
            volumes = pd.Series(0.0, index=df.index)

        # Check for NaN after conversion
        if opens.isna().any() or highs.isna().any() or lows.isna().any() or closes.isna().any():
            nan_locs = [
                i for i, (o, h, low_, c) in enumerate(zip(opens, highs, lows, closes))
                if any(pd.isna(v) for v in (o, h, low_, c))
            ]
            msg = f"Non-numeric values found in candle data at rows: {nan_locs}"
            raise DataError(msg)

        # Build Candle objects
        candles: list[Candle] = []
        for i in range(len(opens)):
            ts = timestamps[i]
            open_price = float(opens.iloc[i])
            high_price = float(highs.iloc[i])
            low_price = float(lows.iloc[i])
            close_price = float(closes.iloc[i])
            volume = float(volumes.iloc[i])

            # Validate candle: high >= max(open, close), low <= min(open, close), high >= low
            if not (high_price >= max(open_price, close_price)):
                msg = (
                    f"Candle at index {i}: high {high_price} < "
                    f"max(open {open_price}, close {close_price})"
                )
                raise DataError(msg)
            if not (low_price <= min(open_price, close_price)):
                msg = (
                    f"Candle at index {i}: low {low_price} > "
                    f"min(open {open_price}, close {close_price})"
                )
                raise DataError(msg)
            if not (high_price >= low_price):
                msg = f"Candle at index {i}: high {high_price} < low {low_price}"
                raise DataError(msg)

            # Parse optional bid/ask if present
            bid: float | None = None
            ask: float | None = None
            if "bid" in df.columns:
                bid_val = pd.to_numeric(df["bid"], errors="coerce")
                if not pd.isna(bid_val.iloc[i]):
                    bid = float(bid_val.iloc[i])
            if "ask" in df.columns:
                ask_val = pd.to_numeric(df["ask"], errors="coerce")
                if not pd.isna(ask_val.iloc[i]):
                    ask = float(ask_val.iloc[i])

            # is_complete flag
            is_complete = True  # Historical data is always complete
            if "is_complete" in df.columns:
                ic = df["is_complete"].iloc[i]
                if ic is not None:
                    is_complete = bool(ic)

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp_utc=ts,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                bid=bid,
                ask=ask,
                source="csv",
                is_complete=is_complete,
            )
            candles.append(candle)

        return candles

    @staticmethod
    def _parse_timestamps(col) -> list[datetime]:
        """Parse a column of timestamp values to timezone-aware UTC datetimes."""
        results: list[datetime] = []
        for val in col:
            val_str = str(val).strip()
            dt_obj = CsvMarketDataProvider._parse_single_timestamp(val_str)
            # Ensure UTC
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=timezone.utc)
            else:
                dt_obj = dt_obj.astimezone(timezone.utc)
            results.append(dt_obj)
        return results

    @staticmethod
    def _parse_single_timestamp(val: str) -> datetime:
        """Parse a single timestamp string.

        Supports:
            - ISO-8601: "2024-01-15T10:30:00Z" or "2024-01-15T10:30:00+00:00"
            - Unix timestamp (seconds or milliseconds)
        """
        from datetime import datetime

        # Try ISO format first
        try:
            parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if parsed.year < 1970:
                # Likely a milliseconds timestamp that was mis-parsed
                raise ValueError("Looks like a ms timestamp")
            return parsed
        except (ValueError, TypeError):
            pass

        # Try Unix timestamp (seconds)
        try:
            ts = float(val)
            if ts > 1e12:
                # Likely milliseconds; convert to seconds
                ts = ts / 1000.0
            elif ts > 1e9 and ts < 1e12:
                # seconds timestamp, ok
                pass
            dt_obj = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt_obj
        except (ValueError, TypeError, OSError):
            pass

        # Try milliseconds timestamp
        try:
            ts = float(val)
            if ts > 1e12:
                dt_obj = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                return dt_obj
            # If we get here, it might be seconds already; fall through to error
        except (ValueError, TypeError, OSError):
            pass

        msg = f"Unable to parse timestamp: {val}"
        raise ValueError(msg)
