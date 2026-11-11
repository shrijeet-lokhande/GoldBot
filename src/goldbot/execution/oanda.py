"""OANDA v20 REST broker adapter — the supported, documented execution API.

This adapter implements the :class:`ExecutionAdapter` contract against
OANDA's official v20 REST API (https://developer.oanda.com/):

- practice host (api-fxpractice.oanda.com) = demo/sandbox environment,
  used for all integration testing; live host (api-fxtrade.oanda.com) is
  only selected via explicit configuration.
- Authentication: OANDA personal access token sent as a Bearer header.
  The token is provided via configuration/environment only and is never
  logged, persisted in the database, or stored in context files.
- Units semantics: OANDA "units" are in ounces of gold; 1 GoldBot lot
  (100 oz) maps to units = lots * 100. Positive units buy, negative sell.
- Every order carries an idempotent clientExtensions.id (DuplicateOrderGuard)
  so retries after uncertain outcomes can be reconciled instead of duplicated.

GoldBot never automates TradingView accounts; execution goes directly to the
broker's documented API.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from goldbot.core.exceptions import GoldBotError, MetadataError
from goldbot.core.instruments import PRIMARY_INSTRUMENT
from goldbot.core.models import (
    InstrumentMetadata,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger("goldbot.broker.oanda")

OANDA_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

INSTRUMENT_MAP = {
    "XAUUSD": "XAU_USD",
}

# OANDA units per GoldBot lot for XAUUSD (1 lot = 100 oz).
UNITS_PER_LOT = 100.0


def instrument_spec_from_oanda(
    details: dict,
    symbol: str,
    units_per_lot: float = UNITS_PER_LOT,
) -> InstrumentMetadata:
    """Convert an OANDA v20 instrument object into verified GoldBot specs.

    Reads the broker's ACTUAL contract specifications (never assumes them):
    - displayPrecision -> tick_size (smallest displayed price increment)
    - tradeUnitsPrecision -> volume step in lots (units precision per oz)
    - minimumTradeSize / maximumOrderUnits -> min/max volume in lots
    - pipLocation / marginRate recorded for margin and risk checks

    Raises MetadataError on any missing or internally inconsistent spec —
    a trade that requires unavailable specs must be rejected, not guessed.
    """
    required = {
        "name": details.get("name"),
        "displayPrecision": details.get("displayPrecision"),
        "tradeUnitsPrecision": details.get("tradeUnitsPrecision"),
        "minimumTradeSize": details.get("minimumTradeSize"),
        "maximumOrderUnits": details.get("maximumOrderUnits"),
        "pipLocation": details.get("pipLocation"),
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise MetadataError(
            f"OANDA instrument spec for {symbol!r} is missing required fields: "
            f"{missing}. Position sizing rejected."
        )

    display_precision = int(details["displayPrecision"])
    units_precision = int(details["tradeUnitsPrecision"])
    minimum_units = float(details["minimumTradeSize"])
    maximum_units = float(details["maximumOrderUnits"])
    pip_location = int(details["pipLocation"])

    if units_per_lot <= 0:
        raise MetadataError("units_per_lot must be positive.")
    if display_precision < 0 or units_precision < 0:
        raise MetadataError(
            f"OANDA spec precisions for {symbol!r} are negative "
            f"(display={display_precision}, units={units_precision})."
        )
    if maximum_units <= 0 or minimum_units <= 0:
        raise MetadataError(
            f"OANDA trade-size bounds for {symbol!r} are non-positive "
            f"(min={minimum_units}, max={maximum_units})."
        )
    if minimum_units > maximum_units:
        raise MetadataError(
            f"Inconsistent OANDA spec for {symbol!r}: minimumTradeSize "
            f"({minimum_units}) exceeds maximumOrderUnits ({maximum_units})."
        )

    quote_currency = details["name"].split("_", 1)[1] if "_" in details["name"] else "USD"
    tick_size = 10.0 ** (-display_precision)
    contract_size = units_per_lot  # 1 GoldBot lot = units_per_lot oz of gold
    tick_value = tick_size * contract_size  # quote-currency value per tick per lot

    metadata = InstrumentMetadata(
        symbol=symbol,
        venue="OANDA",
        asset_type="metal_spot",
        quote_currency=quote_currency,
        contract_size=contract_size,
        tick_size=tick_size,
        tick_value=tick_value,
        volume_step=10.0 ** (-units_precision) / units_per_lot,
        min_volume=minimum_units / units_per_lot,
        max_volume=maximum_units / units_per_lot,
        trading_hours=None,
        margin_rate=float(details["marginRate"]) if details.get("marginRate") else None,
        commission=None,
        swap_long=None,
        swap_short=None,
        verified=True,
        source=f"oanda_v20_instruments(pipLocation={pip_location})",
    )
    if metadata.min_volume is None or metadata.max_volume is None:
        raise MetadataError("converted volumes are missing.")  # defensive
    if metadata.min_volume > metadata.max_volume:
        raise MetadataError(
            f"Converted volume bounds inverted for {symbol!r}: "
            f"min {metadata.min_volume} > max {metadata.max_volume}."
        )
    return metadata


class OandaBrokerAdapter:
    """OANDA v20 REST execution adapter.

    Args:
        account_id: OANDA account ID (e.g. ``101-004-1234567-001``).
        api_token: OANDA personal access token (kept in memory only).
        environment: ``practice`` (default, demo) or ``live``.
        http: injectable HTTP callable ``(method, url, headers, body) ->
            (status, body_dict)`` for testing; defaults to stdlib urllib.
        lots_to_units: conversion factor (100 oz per lot for XAUUSD).
    """

    def __init__(
        self,
        account_id: str,
        api_token: str,
        environment: str = "practice",
        http: Callable[[str, str, dict, dict | None], tuple[int, dict]] | None = None,
        lots_to_units: float = UNITS_PER_LOT,
        symbol: str = PRIMARY_INSTRUMENT.symbol,
    ):
        if environment not in OANDA_HOSTS:
            raise GoldBotError(
                f"OANDA environment must be one of {sorted(OANDA_HOSTS)}, got {environment!r}"
            )
        if not account_id or not api_token:
            raise GoldBotError("OANDA account_id and api_token are required for live trading")
        self.account_id = account_id
        self._token = api_token
        self.environment = environment
        self.base_url = OANDA_HOSTS[environment]
        self._http = http or self._urllib_http
        self.lots_to_units = lots_to_units
        self.symbol = symbol
        self.oanda_instrument = INSTRUMENT_MAP.get(symbol, symbol)
        self._connected = False

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    @staticmethod
    def _urllib_http(method: str, url: str, headers: dict, body: dict | None):
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in headers.items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "UNIX",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        status, payload = self._http(method, url, self._headers(), body)
        if status >= 400:
            detail = payload.get("errorMessage") or payload
            raise GoldBotError(f"OANDA {method} {path} failed ({status}): {detail}")
        return payload

    # ------------------------------------------------------------------
    # Account / connection
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        try:
            self._request("GET", f"/v3/accounts/{self.account_id}/summary")
            return True
        except Exception:
            logger.exception("OANDA health check failed")
            return False

    def reconnect(self) -> bool:
        self._connected = self.health_check()
        return self._connected

    def get_instrument_spec(self, symbol: str | None = None) -> InstrumentMetadata:
        """Fetch the broker's ACTUAL contract specs for the instrument.

        Uses /v3/accounts/{id}/instruments; raises GoldBotError when the
        broker does not list the instrument or the request fails. Account
        currency is read from the account summary so tick values can be
        converted for sizing (see get_quote_to_account_rate).
        """
        sym = symbol or self.symbol
        oanda_name = INSTRUMENT_MAP.get(sym, sym)
        payload = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/instruments?instruments={oanda_name}",
        )
        instruments = payload.get("instruments") or []
        matches = [i for i in instruments if i.get("name") == oanda_name]
        if not matches:
            raise GoldBotError(
                f"OANDA does not list instrument {oanda_name!r} for this account; "
                "refusing to size orders against assumed specs."
            )
        account_currency = self.get_account_summary().get("currency") or "USD"
        spec = instrument_spec_from_oanda(matches[0], sym)
        if account_currency and spec.quote_currency and account_currency != spec.quote_currency:
            rate = self.get_quote_to_account_rate(spec.quote_currency, account_currency)
            # Keep the spec in quote currency; sizing must multiply by `rate`.
            spec.source += f";account_currency={account_currency};quote_to_acct_rate={rate:.10g}"
        return spec

    def get_quote_to_account_rate(self, quote_currency: str, account_currency: str) -> float:
        """Conversion rate quote-currency -> account-currency (rejects on failure).

        Sizing risk in the account currency needs this when the broker
        account is not denominated in the instrument quote currency
        (XAUUSD quotes USD). We ask OANDA for a one-candle price snapshot
        of the direct or inverse pair; if neither exists the trade is
        rejected rather than sized with an assumed rate.
        """
        if quote_currency == account_currency:
            return 1.0
        # Pair A_B's price = B per 1 A. We want rate = account per 1 quote:
        # - pair (account, quote): price = quote per account -> invert
        # - pair (quote, account): price = account per quote -> direct
        for pair, invert in (
            (f"{account_currency}_{quote_currency}", True),
            (f"{quote_currency}_{account_currency}", False),
        ):
            try:
                payload = self._request(
                    "GET",
                    f"/v3/instruments/{pair}/candles?count=1&granularity=S&price=M",
                )
                candles = payload.get("candles") or []
                if candles and candles[-1].get("complete"):
                    close = float(candles[-1]["mid"]["c"])
                    if close > 0:
                        return 1.0 / close if invert else close
            except GoldBotError:
                continue
        raise MetadataError(
            f"Cannot determine conversion rate {quote_currency}->{account_currency} "
            "from broker pricing; position sizing rejected."
        )

    def get_account_summary(self) -> dict:
        """Account balance, margin, P&L (v20 account object)."""
        payload = self._request("GET", f"/v3/accounts/{self.account_id}")
        acct = payload.get("account", {})
        return {
            "broker": "oanda",
            "environment": self.environment,
            "account_id": acct.get("id"),
            "currency": acct.get("currency"),
            "balance": float(acct.get("balance", 0.0)),
            "available_margin": float(acct.get("marginAvailable", 0.0)),
            "used_margin": float(acct.get("marginUsed", 0.0)),
            "unrealised_pnl": float(acct.get("unrealizedPL", 0.0)),
            "open_trade_count": int(acct.get("openTradeCount", 0)),
            "pending_order_count": int(acct.get("pendingOrderCount", 0)),
        }

    def get_account_equity(self) -> float:
        payload = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        acct = payload.get("account", {})
        return float(acct.get("NAV", acct.get("balance", 0.0)))

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def send_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        volume: float,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        timeout_seconds: int = 10,
        client_order_id: str | None = None,
    ) -> Order:
        """Place an order. Volume is in GoldBot lots (converted to units)."""
        if symbol != self.symbol:
            raise GoldBotError(f"adapter bound to {self.symbol}, got {symbol}")
        units = volume * self.lots_to_units
        if side == OrderSide.SELL:
            units = -units
        client_order_id = client_order_id or f"goldbot-{uuid.uuid4().hex[:16]}"

        body: dict[str, Any] = {
            "order": {
                "type": order_type.value.upper(),
                "instrument": self.oanda_instrument,
                "units": str(int(round(units))),
                "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC",
                "clientExtensions": {"id": client_order_id, "tag": "goldbot"},
            }
        }
        if order_type in (OrderType.LIMIT, OrderType.STOP):
            if price is None:
                raise GoldBotError(f"{order_type.value} orders require a price")
            body["order"]["price"] = f"{price:.5f}"
        if stop_loss is not None:
            body["order"]["stopLossOnFill"] = {
                "price": f"{stop_loss:.5f}",
                "timeInForce": "GTC",
            }
        if take_profit is not None:
            body["order"]["takeProfitOnFill"] = {
                "price": f"{take_profit:.5f}",
                "timeInForce": "GTC",
            }

        submitted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        try:
            payload = self._request("POST", f"/v3/accounts/{self.account_id}/orders", body)
        except GoldBotError as exc:
            logger.error("OANDA order submission failed: %s", exc)
            return Order(
                order_id=client_order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                volume=volume,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status=OrderStatus.REJECTED,
                submitted_at=submitted_at,
            )

        order_payload = payload.get("orderCreateTransaction", {})
        order_id = order_payload.get("id") or client_order_id
        # MARKET orders with FOK may fill immediately: check the fill tx.
        fill_tx = payload.get("orderFillTransaction")
        status = OrderStatus.PENDING
        fill_price = None
        filled_at = None
        if fill_tx:
            status = OrderStatus.FILLED
            fill_price = float(fill_tx.get("price", 0.0)) or None
            filled_at = submitted_at
        elif payload.get("orderCancelTransaction"):
            status = OrderStatus.CANCELLED

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            order_type=order_type,
            volume=volume,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=status,
            submitted_at=submitted_at,
            filled_at=filled_at,
            fill_price=fill_price,
        )

    def get_order_state(self, order_id: str) -> OrderStatus:
        payload = self._request("GET", f"/v3/accounts/{self.account_id}/orders/{order_id}")
        order = payload.get("order", {})
        state = order.get("state", "")
        mapping = {
            "PENDING": OrderStatus.PENDING,
            "FILLED": OrderStatus.FILLED,
            "TRIGGERED": OrderStatus.FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
        }
        return mapping.get(state.upper(), OrderStatus.PENDING)

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._request(
                "PUT",
                f"/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
            )
            return True
        except GoldBotError:
            logger.exception("OANDA cancel failed for %s", order_id)
            return False

    def get_pending_orders(self) -> list[dict]:
        payload = self._request("GET", f"/v3/accounts/{self.account_id}/pendingOrders")
        return [
            {
                "order_id": o.get("id"),
                "client_order_id": (o.get("clientExtensions") or {}).get("id"),
                "type": o.get("type"),
                "instrument": o.get("instrument"),
                "units": float(o.get("units", 0.0)),
                "price": o.get("price"),
                "state": o.get("state"),
            }
            for o in payload.get("orders", [])
        ]

    def get_order_history(self, count: int = 50) -> list[dict]:
        payload = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/orders?count={count}&state=ALL",
        )
        return [
            {
                "order_id": o.get("id"),
                "client_order_id": (o.get("clientExtensions") or {}).get("id"),
                "type": o.get("type"),
                "state": o.get("state"),
                "units": o.get("units"),
            }
            for o in payload.get("orders", [])
        ]

    # ------------------------------------------------------------------
    # Positions & reconciliation
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> Position:
        positions = self.get_positions()
        for position in positions:
            if position.symbol == symbol:
                return position
        return Position(
            symbol=symbol, side=OrderSide.BUY, volume=0.0, entry_price=0.0, current_price=0.0
        )

    def get_positions(self) -> list[Position]:
        payload = self._request("GET", f"/v3/accounts/{self.account_id}/positions")
        out: list[Position] = []
        for pos in payload.get("positions", []):
            if pos.get("instrument") != self.oanda_instrument:
                continue
            long_units = float(pos.get("long", {}).get("units", 0.0))
            short_units = float(pos.get("short", {}).get("units", 0.0))
            if long_units > 0:
                out.append(
                    Position(
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        volume=long_units / self.lots_to_units,
                        entry_price=float(pos.get("long", {}).get("averagePrice", 0.0) or 0.0),
                        unrealised_pnl=float(pos.get("long", {}).get("unrealizedPL", 0.0)),
                    )
                )
            elif short_units < 0:
                out.append(
                    Position(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        volume=abs(short_units) / self.lots_to_units,
                        entry_price=float(pos.get("short", {}).get("averagePrice", 0.0) or 0.0),
                        unrealised_pnl=float(pos.get("short", {}).get("unrealizedPL", 0.0)),
                    )
                )
        return out

    def close_position(self, symbol: str = PRIMARY_INSTRUMENT.symbol) -> dict:
        """Market-close the full open position (long and/or short side)."""
        units_signed: float | None = None
        for position in self.get_positions():
            if position.symbol == symbol and position.volume > 0:
                units = position.volume * self.lots_to_units
                units_signed = units if position.side == OrderSide.BUY else -units
                break
        if units_signed is None:
            return {"status": "no_open_position"}
        body = {"longUnits": "ALL"} if units_signed > 0 else {"shortUnits": "ALL"}
        payload = self._request(
            "PUT", f"/v3/accounts/{self.account_id}/positions/{self.oanda_instrument}/close", body
        )
        return {"status": "close_requested", "transactions": list(payload.keys())}

    def reconcile(self, local_open_volume_lots: float) -> dict:
        """Compare GoldBot's local position state with the broker's.

        Returns a discrepancy report; the caller must resolve any mismatch
        before submitting new orders (never blind-retry after uncertainty).
        """
        broker_positions = self.get_positions()
        broker_volume = sum(p.volume for p in broker_positions)
        diff = round(local_open_volume_lots - broker_volume, 6)
        return {
            "agreed": abs(diff) < 1e-6,
            "local_volume_lots": local_open_volume_lots,
            "broker_volume_lots": broker_volume,
            "difference_lots": diff,
        }


__all__ = ["OandaBrokerAdapter", "OANDA_HOSTS", "INSTRUMENT_MAP", "UNITS_PER_LOT"]
