"""GoldBot paper broker - order execution simulation for paper trading.

The paper broker simulates order execution without connecting to a real broker.
It is the default execution adapter for v1 and supports:

- Market and limit order simulation
- Configurable spread, commission, and slippage
- Partial-fill simulation
- Stop-loss and take-profit simulation
- Position and account-equity tracking
- Persistent order state
- A live trade ledger (``get_trades``) for API consumption

Paper broker fills are explicitly SIMULATED and should not be relied upon
as real execution behavior. See the class docstring for assumptions.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from goldbot.core.exceptions import (
    OrderRejectedError,
    OrderTimeoutError,
)
from goldbot.core.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
)
from goldbot.execution.base import ExecutionAdapter

logger = logging.getLogger("goldbot.execution.paper_broker")


class PaperBroker(ExecutionAdapter):
    """Simulates order execution for paper trading.

    This adapter does NOT connect to a real broker. It simulates fills
    based on price proximity to entry, stop, and target levels, with
    configurable slippage and spread. All simulated fills are explicitly
    labeled as such.

    Key assumptions and behaviors:
        - Market orders fill immediately at ``current_price`` +/- spread
          and slippage.
        - Stop-loss and take-profit are simulated by closing the position
          when the simulated price crosses those levels.
        - Partial fills are supported via the partial_fill_probability
          configuration.
        - Commission and spread are deducted from P&L.
        - Order state is persisted to disk (JSON) for reconciliation on
          process restart.

    Attributes:
        symbol: Trading symbol.
        spread: Simulation spread in price units (added to ask for buys,
            subtracted from bid for sells).
        commission: Commission per side (in quote currency or percentage).
        slippage: Maximum slippage in price units.
        partial_fill_probability: Probability [0, 1] of a partial fill.
        timeout_seconds: How long to wait before timing out an order.
        initial_equity: Starting account equity for P&L calculations.
        contract_size: Units per 1.0 lot (e.g. 100 oz per XAUUSD lot).
            P&L per 1.0 price-unit move per lot.
        current_price: The live simulated mid-price. Push new prices via
            :meth:`update_market_price`.
    """

    # -----------------------------------------------------------------
    # Constructor
    # -----------------------------------------------------------------

    def __init__(
        self,
        symbol: str,
        spread: float = 0.0,
        commission: float = 0.0,
        slippage: float = 0.0,
        partial_fill_probability: float = 0.0,
        timeout_seconds: int = 10,
        initial_equity: float = 10_000.0,
        persistence_path: str | Path | None = None,
        contract_size: float = 100.0,
        current_price: float | None = None,
    ):
        self.symbol = symbol
        self.spread = spread
        self.commission = commission
        self.slippage = slippage
        self.partial_fill_probability = max(0.0, min(1.0, partial_fill_probability))
        self.timeout_seconds = timeout_seconds
        self.initial_equity = initial_equity
        self.contract_size = contract_size

        # Live simulated price
        self.current_price: float = current_price if current_price is not None else 1_800.0

        # Order and position state
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        # Closed trades ledger (realised P&L events)
        self.closed_trades: list[dict] = []
        # Cumulative realised P&L of every fully-realised close event
        self._realised_pnl_total: float = 0.0

        # Persistence
        self.persistence_path = Path(persistence_path) if persistence_path else Path(
            f"logs/orders_{symbol}.json"
        )
        self._ensure_dirs()
        self._load_persistence()

    # -----------------------------------------------------------------
    # Lifecycle / persistence
    # -----------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Ensure the persistence directory exists."""
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_persistence(self) -> None:
        """Load previously persisted order/position state from disk."""
        if not self.persistence_path.exists():
            return
        try:
            data = json.loads(self.persistence_path.read_text())
            orders = data.get("orders", []) if isinstance(data, dict) else []
            positions = data.get("positions", []) if isinstance(data, dict) else []

            # Restore the realised P&L ledger and closed-trade history
            if isinstance(data, dict):
                closed = data.get("closed_trades") or []
                if isinstance(closed, list):
                    self.closed_trades = list(closed)
                replay = data.get("realised_pnl_total")
                if isinstance(replay, (int, float)) and replay != 0.0:
                    self._realised_pnl_total = float(replay)
                elif self.closed_trades:
                    self._realised_pnl_total = float(
                        sum(trade.get("pnl", 0.0) for trade in self.closed_trades)
                    )
                price = data.get("current_price")
                if isinstance(price, (int, float)) and price > 0 and not self._positions:
                    self.current_price = float(price)

            for od in orders:
                try:
                    order = Order(
                        order_id=od["order_id"],
                        symbol=od["symbol"],
                        side=OrderSide(od["side"]),
                        order_type=OrderType(od["order_type"]),
                        volume=od["volume"],
                        price=od.get("price"),
                        stop_loss=od.get("stop_loss"),
                        take_profit=od.get("take_profit"),
                        status=OrderStatus(od["status"]),
                        submitted_at=(
                            datetime.fromisoformat(od["submitted_at"])
                            if "submitted_at" in od else datetime.now(timezone.utc)
                        ),
                        filled_at=(
                            datetime.fromisoformat(od["filled_at"])
                            if od.get("filled_at") else None
                        ),
                        fill_price=od.get("fill_price"),
                        filled_volume=od.get("filled_volume"),
                        remaining_volume=od.get("remaining_volume", od["volume"]),
                    )
                    self._orders[order.order_id] = order
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("Skipping malformed persisted order: %s", exc)

            for pd_ in positions:
                try:
                    pos = Position(
                        symbol=pd_["symbol"],
                        side=OrderSide(pd_["side"]),
                        volume=pd_["volume"],
                        entry_price=pd_["entry_price"],
                        current_price=pd_.get("current_price"),
                        unrealised_pnl=pd_.get("unrealised_pnl", 0.0),
                        realised_pnl=pd_.get("realised_pnl", 0.0),
                        stop_loss=pd_.get("stop_loss"),
                        take_profit=pd_.get("take_profit"),
                    )
                    self._positions[pos.symbol] = pos
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("Skipping malformed persisted position: %s", exc)

            if self.current_price == 1_800.0 and self._positions:
                # Restore price context from persisted state
                first_price = next(iter(self._positions.values())).current_price
                self.current_price = first_price or self.current_price

            logger.info(
                "Loaded persisted state: %d orders, %d positions",
                len(data.get("orders", [])), len(data.get("positions", [])),
            )
        except Exception as exc:
            logger.warning("Failed to load persistence state: %s", exc)

    def _save_persistence(self) -> None:
        """Persist current order and position state to disk."""
        try:
            orders_data = [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "volume": o.volume,
                    "price": o.price,
                    "stop_loss": o.stop_loss,
                    "take_profit": o.take_profit,
                    "status": o.status.value,
                    "submitted_at": o.submitted_at.isoformat(),
                    "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                    "fill_price": o.fill_price,
                    "filled_volume": o.filled_volume,
                    "remaining_volume": o.remaining_volume,
                }
                for o in self._orders.values()
            ]
            positions_data = [
                {
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "volume": p.volume,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealised_pnl": p.unrealised_pnl,
                    "realised_pnl": p.realised_pnl,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                }
                for p in self._positions.values()
            ]
            data = {
                "orders": orders_data,
                "positions": positions_data,
                "closed_trades": self.closed_trades,
                "realised_pnl_total": self._realised_pnl_total,
                "current_price": self.current_price,
            }
            self.persistence_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("Failed to save persistence state: %s", exc)

    # -----------------------------------------------------------------
    # Market price updates (feeds the simulation)
    # -----------------------------------------------------------------

    def update_market_price(self, price: float, timestamp: datetime | None = None) -> list[dict]:
        """Push a new simulated market price and evaluate SL/TP.

        This is the entry point the trading loop (or API) calls on every
        simulated tick. Any open position whose SL/TP triggers at this
        price is closed here, and the closed trade is appended to the
        ledger.

        Returns:
            The list of trades closed by this price update (possibly empty).
        """
        self.current_price = float(price)

        closed: list[dict] = []
        for pos in list(self._positions.values()):
            if pos.volume <= 0:
                continue
            pos.current_price = self.current_price
            pos.unrealised_pnl = self._calculate_pnl(pos, self.current_price)

            sl = pos.stop_loss
            tp = pos.take_profit
            if sl is not None and self._price_triggers_sl(pos, self.current_price, sl):
                close_trade = self._close_position(
                    pos, sl, reason="stop_loss", timestamp=timestamp
                )
                closed.append(close_trade)
            elif tp is not None and self._price_triggers_tp(pos, self.current_price, tp):
                close_trade = self._close_position(
                    pos, tp, reason="take_profit", timestamp=timestamp
                )
                closed.append(close_trade)

        if closed:
            self._save_persistence()
        return closed

    def set_price(self, price: float) -> None:
        """Set the simulated mid-price without any SL/TP evaluation."""
        self.current_price = float(price)

    # -----------------------------------------------------------------
    # Execution adapter interface
    # -----------------------------------------------------------------

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
        """Send a new order to the paper broker.

        In simulation mode, the order is immediately processed (filled,
        partially filled, or rejected) based on the configuration.
        The order book is not modeled; there is no order book depth.
        """
        # Validate
        if volume <= 0:
            raise OrderRejectedError(f"Invalid volume: {volume}. Must be positive.")

        if order_type == OrderType.LIMIT and price is None:
            raise OrderRejectedError("Limit order requires a price.")

        # Coerce enum inputs
        side = side if isinstance(side, OrderSide) else OrderSide(side)
        order_type = order_type if isinstance(order_type, OrderType) else OrderType(order_type)

        # Create the order
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            volume=volume,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=OrderStatus.PENDING,
            submitted_at=now,
        )

        self._orders[order_id] = order

        # Immediately process in simulation mode
        self._process_order_immediately(order)

        # Persist state
        self._save_persistence()

        return order

    def _process_order_immediately(self, order: Order) -> None:
        """Simulate immediate order fill based on configuration.

        The fill price incorporates:
            - The spread (bid/ask differential)
            - Directional slippage (worse fill for the side of the trade)
        """
        volume = order.volume

        if order.order_type == OrderType.MARKET:
            # Market order: fill at the live simulated price +/- spread and slippage
            mid_price = self._get_mid_price()
            if order.side == OrderSide.BUY:
                fill_price = mid_price + self.slippage / 2.0 + self.spread / 2.0
            else:
                fill_price = mid_price - self.slippage / 2.0 - self.spread / 2.0

            # Partial fill simulation
            if self.partial_fill_probability > 0.0:
                import random
                if random.random() < self.partial_fill_probability:  # noqa: S311 (simulation)
                    fill_ratio = random.uniform(0.3, 0.7)  # noqa: S311 (simulation)
                    order.filled_volume = volume * fill_ratio
                    order.remaining_volume = volume - order.filled_volume
                else:
                    order.filled_volume = volume
                    order.remaining_volume = 0.0
            else:
                order.filled_volume = volume
                order.remaining_volume = 0.0

            order.fill_price = fill_price
            order.filled_at = datetime.now(timezone.utc)
            order.status = OrderStatus.FILLED

            # Update position from the fill
            self._update_position_from_fill(order, fill_price)

        elif order.order_type == OrderType.LIMIT:
            market_price = self._get_mid_price()
            should_fill = (
                (order.side == OrderSide.BUY and market_price <= order.price)
                or (order.side == OrderSide.SELL and market_price >= order.price)
            )
            if should_fill:
                fill_price = order.price
                order.filled_volume = volume
                order.remaining_volume = 0.0
                order.fill_price = fill_price
                order.filled_at = datetime.now(timezone.utc)
                order.status = OrderStatus.FILLED
                self._update_position_from_fill(order, fill_price)
            else:
                order.status = OrderStatus.REJECTED
                logger.debug(
                    "Limit order %s not filled; market %s vs limit %s",
                    order.order_id, market_price, order.price,
                )
        else:
            order.status = OrderStatus.REJECTED
            logger.debug("Order type %s not simulated; rejected", order.order_type)

        logger.info(
            "Order %s processed: type=%s, side=%s, vol=%s, fill_price=%s, status=%s",
            order.order_id, order.order_type, order.side, order.volume,
            order.fill_price, order.status.value,
        )

    def _get_mid_price(self) -> float:
        """Get the current simulated mid-price for the symbol."""
        return self.current_price

    # -----------------------------------------------------------------
    # Position management
    # -----------------------------------------------------------------

    def _update_position_from_fill(self, order: Order, fill_price: float) -> None:
        """Update or create position based on an order fill.

        If a position already exists for the symbol in the opposing side,
        the fill reduces/reverses it; same side adds to it (averaged).
        """
        side = order.side
        volume = order.filled_volume if order.filled_volume is not None else order.volume
        symbol = order.symbol

        existing = self._positions.get(symbol)
        if existing is not None and existing.volume > 0 and existing.side == side:
            # Adding to existing position of same side
            prev = existing.entry_price * existing.volume
            existing.volume += volume
            existing.entry_price = (
                (prev + fill_price * volume) / existing.volume
                if existing.volume else fill_price
            )

            existing.current_price = self.current_price
            existing.unrealised_pnl = self._calculate_pnl(existing, self.current_price)
            pos = existing
        elif existing is not None and existing.volume > 0 and existing.side != side:
            # Reducing or reversing
            close_volume = min(existing.volume, volume)
            pnl = self._pnl_for(existing, fill_price, close_volume)
            # Commission applied symmetrically
            pnl -= self.commission * close_volume
            existing.realised_pnl += pnl
            self._record_closed_trade(existing, fill_price, close_volume, pnl,
                                      reason="manual_close", closed_at=datetime.now(timezone.utc))
            remaining = volume - close_volume
            if remaining <= 0:
                self._positions.pop(symbol, None)
                pos = Position(symbol=symbol, side=side, volume=0.0, entry_price=fill_price,
                               current_price=self.current_price)
            else:
                pos = Position(symbol=symbol, side=side, volume=remaining, entry_price=fill_price,
                               current_price=self.current_price,
                               stop_loss=order.stop_loss, take_profit=order.take_profit)
                self._positions[symbol] = pos
        else:
            pos = Position(
                symbol=symbol,
                side=side,
                volume=volume,
                entry_price=fill_price,
                current_price=self.current_price,
                unrealised_pnl=0.0,
                realised_pnl=0.0,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
            self._positions[symbol] = pos

        self._attach_sl_tp_to_position(order)

        # Immediately evaluate SL/TP against the fill price
        if pos.volume > 0:
            self._check_sl_tp(pos, self.current_price)

    def _pnl_for(self, position: Position, price: float, volume: float) -> float:
        """P&L in quote currency for `volume` lots from entry to `price`."""
        if position.side == OrderSide.BUY:
            return (price - position.entry_price) * volume * self.contract_size
        return (position.entry_price - price) * volume * self.contract_size

    def _calculate_pnl(self, position: Position, current_price: float) -> float:
        """Unrealised P&L (quote currency) for the whole position."""
        return self._pnl_for(position, current_price, position.volume)

    def _attach_sl_tp_to_position(self, order: Order) -> None:
        """Attach stop-loss and take-profit levels to the resulting position."""
        symbol = order.symbol
        if symbol not in self._positions:
            return
        pos = self._positions[symbol]
        if order.stop_loss is not None:
            pos.stop_loss = order.stop_loss
        if order.take_profit is not None:
            pos.take_profit = order.take_profit

    def _check_sl_tp(self, position: Position, current_price: float) -> None:
        """Close the position if SL/TP triggers at `current_price`."""
        sl = position.stop_loss
        tp = position.take_profit
        if position.volume <= 0:
            return

        if sl is not None and self._price_triggers_sl(position, current_price, sl):
            self._close_position(position, sl, reason="stop_loss",
                                 timestamp=datetime.now(timezone.utc))
        elif tp is not None and self._price_triggers_tp(position, current_price, tp):
            self._close_position(position, tp, reason="take_profit",
                                 timestamp=datetime.now(timezone.utc))

    def _close_position(
        self,
        position: Position,
        close_price: float,
        reason: str,
        timestamp: datetime | None = None,
    ) -> dict:
        """Close a position at `close_price`, record the trade, remove it."""
        timestamp = timestamp or datetime.now(timezone.utc)
        pnl = self._pnl_for(position, close_price, position.volume)
        pnl -= self.commission * position.volume

        trade = {
            "trade_id": str(uuid.uuid4()),
            "symbol": position.symbol,
            "side": position.side.value,
            "volume": position.volume,
            "entry_price": position.entry_price,
            "close_price": close_price,
            "pnl": pnl,
            "entry_time": (
                position.opened_at.isoformat()
                if getattr(position, "opened_at", None) else None
            ),
            "close_time": timestamp.isoformat(),
            "reason": reason,
        }
        trade["entry_time"] = trade["entry_time"] or timestamp.isoformat()

        position.realised_pnl += pnl
        position.unrealised_pnl = 0.0
        position.volume = 0.0
        position.current_price = close_price

        self._realised_pnl_total += pnl
        self.closed_trades.append(trade)
        self._positions.pop(position.symbol, None)

        logger.info(
            "Position closed for %s %s @ %.2f: reason=%s P&L=%.2f",
            position.side.value, position.symbol, close_price, reason, pnl,
        )
        return trade

    def _record_closed_trade(self, position: Position, close_price: float,
                             volume: float, pnl: float, reason: str,
                             closed_at: datetime) -> None:
        trade = {
            "trade_id": str(uuid.uuid4()),
            "symbol": position.symbol,
            "side": position.side.value,
            "volume": volume,
            "entry_price": position.entry_price,
            "close_price": close_price,
            "pnl": pnl,
            "close_time": closed_at.isoformat(),
            "reason": reason,
        }
        self.closed_trades.append(trade)
        self._realised_pnl_total += pnl

    def _price_triggers_sl(self, position: Position, current_price: float, sl: float) -> bool:
        """For long: triggered if price <= sl. For short: price >= sl."""
        if position.side == OrderSide.BUY:
            return current_price <= sl
        return current_price >= sl

    def _price_triggers_tp(self, position: Position, current_price: float, tp: float) -> bool:
        """For long: triggered if price >= tp. For short: price <= tp."""
        if position.side == OrderSide.BUY:
            return current_price >= tp
        return current_price <= tp

    # -----------------------------------------------------------------
    # Account queries
    # -----------------------------------------------------------------

    def get_open_position(self, symbol: str) -> Optional[Position]:
        """Get the open position for a symbol, or None when flat."""
        pos = self._positions.get(symbol)
        if pos is not None and pos.volume > 0:
            return pos
        return None

    def get_position(self, symbol: str) -> Position:
        """Get the position for a symbol (flat Position when none open)."""
        pos = self.get_open_position(symbol)
        if pos is not None:
            return pos
        return Position(
            symbol=symbol,
            side=OrderSide.BUY,
            volume=0.0,
            entry_price=0.0,
            current_price=self.current_price,
            unrealised_pnl=0.0,
            realised_pnl=0.0,
        )

    def get_positions(self) -> list[Position]:
        """All currently open positions."""
        return [p for p in self._positions.values() if p.volume > 0]

    def get_trades(self, limit: int | None = None) -> list[dict]:
        """The realised (closed) trade ledger, newest first."""
        trades = list(reversed(self.closed_trades))
        if limit is not None:
            trades = trades[:limit]
        return trades

    def get_account_equity(self) -> float:
        """Equity = initial + realised P&L + unrealised P&L."""
        unrealised = 0.0
        for pos in self._positions.values():
            if pos.volume > 0:
                pos.current_price = self.current_price
                pos.unrealised_pnl = self._calculate_pnl(pos, self.current_price)
                unrealised += pos.unrealised_pnl
        return self.initial_equity + self._realised_pnl_total + unrealised

    def close_position(self, symbol: str) -> dict | None:
        """Manually close the open position at the current market price."""
        pos = self.get_open_position(symbol)
        if pos is None:
            return None
        trade = self._close_position(pos, self.current_price, reason="manual_close",
                                     timestamp=datetime.now(timezone.utc))
        self._save_persistence()
        return trade

    # -----------------------------------------------------------------
    # Order management
    # -----------------------------------------------------------------

    def get_orders(self) -> list[Order]:
        """All orders, newest first."""
        return list(reversed(list(self._orders.values())))

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order (status -> CANCELLED)."""
        order = self._orders.get(order_id)
        if order is None:
            return False
        order.status = OrderStatus.CANCELLED
        self._save_persistence()
        return True

    def get_order_state(self, order_id: str) -> OrderStatus:
        """Get the current state of an order."""
        order = self._orders.get(order_id)
        if order is None:
            return OrderStatus.REJECTED
        return order.status

    # -----------------------------------------------------------------
    # Adapter lifecycle
    # -----------------------------------------------------------------

    def reconnect(self) -> bool:
        """Reconnect ('reload persistence'). Always succeeds in simulation."""
        self._load_persistence()
        return True

    def health_check(self) -> bool:
        """The simulation is always healthy."""
        return True

    # -----------------------------------------------------------------
    # Signal submission convenience
    # -----------------------------------------------------------------

    def submit_signal(
        self,
        signal: Signal,
        entry_price: float,
        stop_price: float,
        volume: float = 1.0,
        take_profit: float | None = None,
        timeout_seconds: int = 10,
    ) -> Order | None:
        """Convert a signal into an order request and submit it.

        The risk engine must have approved the signal and provided the
        position size (`volume`).
        """
        direction = (
            signal.direction.lower() if isinstance(signal.direction, str)
            else str(signal.direction)
        )
        side = OrderSide.BUY if direction in ("long", "buy") else OrderSide.SELL

        try:
            order = self.send_order(
                symbol=signal.symbol,
                side=side,
                order_type=OrderType.MARKET,
                volume=volume,
                price=None,
                stop_loss=stop_price,
                take_profit=take_profit,
                timeout_seconds=timeout_seconds,
            )
            return order
        except (OrderRejectedError, OrderTimeoutError) as exc:
            logger.warning("Signal submission rejected: %s", exc)
            return None
