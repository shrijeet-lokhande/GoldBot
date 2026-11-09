"""GoldBot core models and configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Timestamp type
# ---------------------------------------------------------------------------

Timestamp = datetime


# ---------------------------------------------------------------------------
# Signal direction — used before Signal model is defined
# ---------------------------------------------------------------------------


class SignalDirection:
    """Direction of a trade signal."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

    @classmethod
    def from_string(cls, s: str) -> str:
        s = s.lower().strip()
        if s in ("long", "buy"):
            return cls.LONG
        if s in ("short", "sell"):
            return cls.SHORT
        return cls.FLAT


# ---------------------------------------------------------------------------
# Signal reason codes
# ---------------------------------------------------------------------------


class SignalReason:
    """Codified reason for a signal accept/reject."""

    EMA_FAST_ABOVE_EMA_LONG = "ema_fast_above_ema_long"
    EMA_FAST_BELOW_EMA_LONG = "ema_fast_below_ema_long"
    RSI_ABOVE_THRESHOLD = "rsi_above_threshold"
    RSI_BELOW_THRESHOLD = "rsi_below_threshold"
    BULLISH_CANDLE_CONFIRMED = "bullish_candle_confirmed"
    BEARISH_CANDLE_CONFIRMED = "bearish_candle_confirmed"
    MINIMUM_ADX_FILTER = "minimum_adx_filter"
    DUPLICATE_SIGNAL = "duplicate_signal"
    INSUFFICIENT_DATA = "insufficient_data"
    CANDLE_NOT_COMPLETE = "candle_not_complete"


# ---------------------------------------------------------------------------
# Side / Order side
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    """Side of an order: buy (long) or sell (short)."""

    BUY = "buy"
    SELL = "sell"


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    """Lifecycle status of an order."""

    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Order type
# ---------------------------------------------------------------------------


class OrderType(str, Enum):
    """Order execution type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good 'til cancelled
    IOC = "IOC"  # Immediate or cancel
    FOK = "FOK"  # Fill or kill


# ---------------------------------------------------------------------------
# Candle domain model
# ---------------------------------------------------------------------------


class Candle:
    """Normalized OHLCV candle with metadata."""

    __slots__ = (
        "symbol",
        "timeframe",
        "timestamp_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bid",
        "ask",
        "source",
        "is_complete",
    )

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        timestamp_utc: Timestamp,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        bid: float | None = None,
        ask: float | None = None,
        source: str = "unknown",
        is_complete: bool = True,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.timestamp_utc = timestamp_utc
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.bid = bid
        self.ask = ask
        self.source = source
        self.is_complete = is_complete

    # Derived properties
    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    def __repr__(self) -> str:
        return (
            f"Candle(symbol={self.symbol!r}, tf={self.timeframe}, "
            f"t={self.timestamp_utc.isoformat()}, o={self.open}, h={self.high}, "
            f"l={self.low}, c={self.close}, vol={self.volume}, "
            f"complete={self.is_complete})"
        )


# ---------------------------------------------------------------------------
# Quote domain model
# ---------------------------------------------------------------------------


class Quote:
    """Bid/ask quote snapshot."""

    __slots__ = ("bid", "ask", "timestamp_utc", "source")

    def __init__(
        self,
        bid: float,
        ask: float,
        timestamp_utc: Timestamp | None = None,
        source: str = "unknown",
    ):
        self.bid = bid
        self.ask = ask
        self.timestamp_utc = timestamp_utc or datetime.now(timezone.utc)
        self.source = source

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2.0

    def __repr__(self) -> str:
        return f"Quote(bid={self.bid}, ask={self.ask}, mid={self.mid_price:.2f})"


# ---------------------------------------------------------------------------
# Instrument metadata
# ---------------------------------------------------------------------------


class InstrumentMetadata:
    """Verified instrument/contract specifications.

    All fields should be populated from verified broker/exchange metadata.
    Never assume or guess values — if unknown, keep as None and reject
    trades that require unverified metadata.
    """

    __slots__ = (
        "symbol",
        "venue",
        "asset_type",
        "quote_currency",
        "contract_size",
        "tick_size",
        "tick_value",
        "volume_step",
        "min_volume",
        "max_volume",
        "trading_hours",
        "margin_rate",
        "commission",
        "swap_long",
        "swap_short",
        "verified",
        "source",
    )

    def __init__(
        self,
        symbol: str,
        venue: str | None = None,
        asset_type: str | None = None,
        quote_currency: str = "USD",
        contract_size: float | None = None,
        tick_size: float | None = None,
        tick_value: float | None = None,
        volume_step: float | None = None,
        min_volume: float | None = None,
        max_volume: float | None = None,
        trading_hours: dict | None = None,
        margin_rate: float | None = None,
        commission: float | None = None,
        swap_long: float | None = None,
        swap_short: float | None = None,
        verified: bool = False,
        source: str = "unknown",
    ):
        self.symbol = symbol
        self.venue = venue
        self.asset_type = asset_type
        self.quote_currency = quote_currency
        self.contract_size = contract_size
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.volume_step = volume_step
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.trading_hours = trading_hours
        self.margin_rate = margin_rate
        self.commission = commission
        self.swap_long = swap_long
        self.swap_short = swap_short
        self.verified = verified
        self.source = source

    @property
    def is_verified(self) -> bool:
        return self.verified

    def __repr__(self) -> str:
        return (
            f"InstrumentMetadata(symbol={self.symbol}, verified={self.verified}, "
            f"asset_type={self.asset_type}, venue={self.venue})"
        )


# ---------------------------------------------------------------------------
# Signal domain model
# ---------------------------------------------------------------------------


class Signal:
    """Structured trade signal from the strategy engine.

    The strategy engine proposes signals; the risk engine approves/modifies/
    rejects them. This model carries all information needed for risk evaluation
    and order construction. Never place orders directly from a Signal.

    Attributes:
        signal_id: Unique identifier for this signal.
        symbol: Instrument symbol.
        direction: long | short | flat.
        created_at_utc: When the signal was generated (candle close time).
        reference_price: Price at which the signal was generated (typically
            the candle close).
        stop_distance: Distance to stop loss in price units.
        take_profit_multiple: Risk/reward multiple (e.g. 2.0 means 1:2 R/R).
        timeframe: The candle timeframe the signal is based on.
        strategy_version: Strategy version string for tracking.
        reason_codes: List of reason codes explaining why this setup was taken.
        indicator_snapshot: Snapshot of indicator values at signal time.
    """

    __slots__ = (
        "signal_id",
        "symbol",
        "direction",
        "created_at_utc",
        "reference_price",
        "stop_distance",
        "take_profit_multiple",
        "timeframe",
        "strategy_version",
        "reason_codes",
        "indicator_snapshot",
    )

    def __init__(
        self,
        symbol: str,
        direction: str,
        created_at_utc: Timestamp,
        reference_price: float,
        stop_distance: float,
        take_profit_multiple: float,
        timeframe: str,
        strategy_version: str = "1.0.0",
        reason_codes: list[str] | None = None,
        indicator_snapshot: dict | None = None,
    ):
        self.signal_id = f"{symbol}_{direction}_{int(created_at_utc.timestamp())}"
        self.symbol = symbol
        self.direction = direction
        self.created_at_utc = created_at_utc
        self.reference_price = reference_price
        self.stop_distance = stop_distance
        self.take_profit_multiple = take_profit_multiple
        self.timeframe = timeframe
        self.strategy_version = strategy_version
        self.reason_codes = reason_codes or []
        self.indicator_snapshot = indicator_snapshot or {}

    def __repr__(self) -> str:
        return (
            f"Signal(symbol={self.symbol}, direction={self.direction}, "
            f"ss={self.signal_id}, rfr={self.reason_codes})"
        )


# ---------------------------------------------------------------------------
# Indicator result model
# ---------------------------------------------------------------------------


class IndicatorResult:
    """Container for indicator calculation results.

    Holds the computed value and any additional metadata from an indicator.
    """

    __slots__ = ("name", "value", "timestamp")

    def __init__(self, name: str, value: float | None = None, timestamp: Timestamp | None = None):
        self.name = name
        self.value = value
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return f"IndicatorResult(name={self.name!r}, value={self.value!r})"


# ---------------------------------------------------------------------------
# Order domain model
# ---------------------------------------------------------------------------


class Order:
    """Represents a broker order submitted by the execution layer.

    Orders flow through this lifecycle:
        PENDING -> FILLED/PARTIAL/CANCELLED/REJECTED/TIMEOUT

    Attributes:
        order_id: Unique identifier.
        symbol: Instrument symbol.
        side: OrderSide.BUY or OrderSide.SELL.
        order_type: OrderType.MARKET, LIMIT, etc.
        volume: Ordered volume in lots.
        price: Limit price (None for MARKET).
        stop_loss: Stop loss price (for stop orders or attached to position).
        take_profit: Take profit price.
        status: Current OrderStatus.
        submitted_at: When the order was submitted.
        filled_at: When the order was filled (None if not filled).
        fill_price: Execution price (None if not filled).
        remaining_volume: Still-unfilled volume.
    """

    __slots__ = (
        "order_id",
        "symbol",
        "side",
        "order_type",
        "volume",
        "price",
        "stop_loss",
        "take_profit",
        "status",
        "submitted_at",
        "filled_at",
        "fill_price",
        "filled_volume",
        "remaining_volume",
    )

    def __init__(
        self,
        order_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        volume: float,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        status: OrderStatus = OrderStatus.PENDING,
        submitted_at: datetime | None = None,
        filled_at: float | datetime | None = None,
        fill_price: float | None = None,
        filled_volume: float | None = None,
        remaining_volume: float | None = None,
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side if isinstance(side, OrderSide) else OrderSide(side)
        self.order_type = order_type if isinstance(order_type, OrderType) else OrderType(order_type)
        self.volume = volume
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.status = status if isinstance(status, OrderStatus) else OrderStatus(status)
        self.submitted_at = submitted_at or datetime.now(timezone.utc)
        self.filled_at: datetime | None = None
        if isinstance(filled_at, datetime):
            self.filled_at = filled_at
        elif isinstance(filled_at, float):
            self.filled_at = datetime.fromtimestamp(filled_at, tz=timezone.utc)
        else:
            self.filled_at = filled_at
        self.fill_price = fill_price
        self.filled_volume = filled_volume
        self.remaining_volume = remaining_volume if remaining_volume is not None else volume

    @property
    def is_filled(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.PARTIAL)

    @property
    def is_complete(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.PARTIAL,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.TIMEOUT,
        )

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, sym={self.symbol}, side={self.side.value}, "
            f"type={self.order_type.value}, vol={self.volume}, status={self.status.value})"
        )


# ---------------------------------------------------------------------------
# Fill event
# ---------------------------------------------------------------------------


class FillEvent:
    """Event emitted when an order is filled.

    Records the fill details for audit and P&L calculation.
    """

    __slots__ = ("order_id", "symbol", "side", "volume", "price", "timestamp", "commission")

    def __init__(
        self,
        order_id: str,
        symbol: str,
        side: OrderSide,
        volume: float,
        price: float,
        timestamp: datetime,
        commission: float = 0.0,
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.volume = volume
        self.price = price
        self.timestamp = timestamp
        self.commission = commission

    def __repr__(self) -> str:
        return f"FillEvent(order={self.order_id}, vol={self.volume}, price={self.price})"


# ---------------------------------------------------------------------------
# Position domain model
# ---------------------------------------------------------------------------


class Position:
    """Represents an open position in the account.

    Positions are tracked for unrealised P&L calculation and risk limit checks.
    Positions are closed when opposing orders are filled or SL/TP is triggered.
    """

    __slots__ = (
        "symbol",
        "side",
        "volume",
        "entry_price",
        "current_price",
        "unrealised_pnl",
        "realised_pnl",
        "stop_loss",
        "take_profit",
    )

    def __init__(
        self,
        symbol: str,
        side: OrderSide,
        volume: float,
        entry_price: float,
        current_price: float | None = None,
        unrealised_pnl: float = 0.0,
        realised_pnl: float = 0.0,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ):
        self.symbol = symbol
        self.side = side if isinstance(side, OrderSide) else OrderSide(side)
        self.volume = volume
        self.entry_price = entry_price
        self.current_price = current_price if current_price is not None else entry_price
        self.unrealised_pnl = unrealised_pnl
        self.realised_pnl = realised_pnl
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    @property
    def pnl_percent(self) -> float:
        """Percentage P&L from entry price."""
        if self.entry_price == 0:
            return 0.0
        if self.side.name == "BUY":  # Long
            return (self.current_price - self.entry_price) / self.entry_price * 100.0
        else:  # Short
            return (self.entry_price - self.current_price) / self.entry_price * 100.0

    def __repr__(self) -> str:
        return (
            f"Position(sym={self.symbol}, side={self.side.value}, "
            f"vol={self.volume}, entry={self.entry_price}, "
            f"current={self.current_price}, P&L={self.unrealised_pnl:.2f})"
        )


# ---------------------------------------------------------------------------
# Order event
# ---------------------------------------------------------------------------


class OrderEvent:
    """Event emitted during order lifecycle transitions."""

    __slots__ = ("order_id", "symbol", "event", "details")

    def __init__(
        self,
        order_id: str,
        symbol: str,
        event: str,
        details: dict | None = None,
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.event = event
        self.details = details or {}

    def __repr__(self) -> str:
        return f"OrderEvent(order={self.order_id}, event={self.event})"


# ---------------------------------------------------------------------------
# Data quality status
# ---------------------------------------------------------------------------


class DataQualityStatus:
    """Status of data quality for a given data source."""

    GOOD = "good"
    STALE = "stale"
    MALFORMED = "malformed"
    MISSING = "missing"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Convenience aliases (importable from goldbot.core)
# ---------------------------------------------------------------------------

# SignalDirection is defined above; re-export for convenience
__all__ = [
    "UTC",
    "Timestamp",
    "SignalDirection",
    "SignalReason",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "TimeInForce",
    "Candle",
    "Quote",
    "InstrumentMetadata",
    "Signal",
    "Order",
    "FillEvent",
    "Position",
    "OrderEvent",
    "DataQualityStatus",
    "IndicatorResult",
]
