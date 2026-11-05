"""GoldBot market data provider protocol and types."""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Protocol, runtime_checkable

from goldbot.core.models import Candle, InstrumentMetadata, Quote

__all__ = [
    "MarketDataProviderProtocol",
    "Candle",
    "Quote",
    "InstrumentMetadata",
    "DataQualityStatus",
]


class DataQualityStatus:
    """Status of data quality for a given data source."""

    GOOD = "good"
    STALE = "stale"
    MALFORMED = "malformed"
    MISSING = "missing"
    UNKNOWN = "unknown"


@runtime_checkable
class MarketDataProviderProtocol(Protocol):
    """Protocol/interface for market data providers.

    Implementors must provide methods for historical bars, latest bar,
    quotes, and instrument metadata. The implementations should handle
    normalization and validation internally, raising appropriate
    GoldBot exceptions on failure.
    """

    @abstractmethod
    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Get historical OHLCV candles for the given symbol and timeframe.

        Args:
            symbol: The instrument symbol (e.g. "XAUUSD").
            timeframe: The candle timeframe (e.g. "15m", "1h").
            start: Start datetime (inclusive, UTC).
            end: End datetime (inclusive, UTC).

        Returns:
            A list of Candle objects, sorted by timestamp ascending.
        """
        ...

    @abstractmethod
    def get_latest_bar(self, symbol: str, timeframe: str) -> Candle | None:
        """Get the latest completed bar for the given symbol and timeframe.

        Args:
            symbol: The instrument symbol.
            timeframe: The candle timeframe.

        Returns:
            A Candle if available, None if no data.
        """
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote | None:
        """Get the current bid/ask quote for the given symbol.

        Args:
            symbol: The instrument symbol.

        Returns:
            A Quote if available, None if not supported.
        """
        ...

    @abstractmethod
    def get_instrument_metadata(self, symbol: str) -> InstrumentMetadata:
        """Get verified instrument metadata (contract size, tick size, etc.).

        Args:
            symbol: The instrument symbol.

        Returns:
            InstrumentMetadata with verified specifications.
        """
        ...
