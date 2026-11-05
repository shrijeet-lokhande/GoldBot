"""GoldBot execution interface - the contract that all execution adapters must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from goldbot.core.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
)


class ExecutionAdapter(ABC):
    """Abstract base class for execution adapters (paper or live).

    All methods should raise GoldBot exceptions on failure rather than
    silently failing. The adapter is the only component that communicates
    with the broker/API.
    """

    @abstractmethod
    def send_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        volume: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        timeout_seconds: int = 10,
    ) -> Order:
        """Send a new order to the broker.

        Args:
            symbol: Instrument symbol.
            side: Order side (buy/long or sell/short).
            order_type: Market, limit, stop, etc.
            volume: Order volume in lots.
            price: Limit price (for limit orders) or None for market.
            stop_loss: Stop loss price.
            take_profit: Take profit price.
            timeout_seconds: Maximum time to wait for order fill.

        Returns:
            An Order object representing the submitted order.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order.

        Args:
            order_id: The order ID to cancel.

        Returns:
            True if cancellation was successful.
        """
        ...

    @abstractmethod
    def get_order_state(self, order_id: str) -> OrderStatus:
        """Get the current state of an order.

        Args:
            order_id: The order ID to query.

        Returns:
            The current OrderStatus.
        """
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        """Get the current position for a symbol.

        Args:
            symbol: Instrument symbol.

        Returns:
            Position object with current exposure.
        """
        ...

    @abstractmethod
    def get_account_equity(self) -> float:
        """Get the current account equity.

        Returns:
            Current account equity in quote currency.
        """
        ...

    @abstractmethod
    def reconnect(self) -> bool:
        """Reconnect to the broker API after a disconnection.

        Returns:
            True if reconnection was successful.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the execution adapter is healthy and connected.

        Returns:
            True if the adapter is healthy.
        """
        ...

    def submit_signal(
        self,
        signal: Signal,
        entry_price: float,
        stop_price: float,
        timeout_seconds: int = 10,
    ) -> Optional[Order]:
        """Convenience method: convert a signal into an order request.

        This is a helper that strategy/risk code can call. The actual
        order sending is performed by the specific adapter implementation.

        Args:
            signal: The signal to execute.
            entry_price: Entry price for the order.
            stop_price: Stop loss price.
            timeout_seconds: Timeout for order wait.

        Returns:
            Order object if submitted, None if rejected.
        """
        # Basic validation
        if signal.direction not in ("long", "buy", "short", "sell"):
            return None

        side = OrderSide.BUY if signal.direction in ("long", "buy") else OrderSide.SELL

        # Determine order type
        order_type = OrderType.MARKET

        return self.send_order(
            symbol=signal.symbol,
            side=side,
            order_type=order_type,
            volume=signal.stop_distance,  # placeholder; real size from risk engine
            price=None,
            stop_loss=stop_price,
            take_profit=None,
            timeout_seconds=timeout_seconds,
        )
