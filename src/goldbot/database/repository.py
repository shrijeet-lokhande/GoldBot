"""Optional database mirroring of engine state.

``DatabaseSink`` subscribes to :class:`goldbot.engine.TradingEngine` events
and mirrors proposals, orders and closed trades into the SQL schema managed
by Alembic. It is strictly optional: paper sessions remain fully functional
with the JSON ledger alone. Enable by configuring ``settings.database_url``
(e.g. ``GOLD_DATABASE_URL=postgresql+psycopg://...``).

The sink is defensive by design: it must never break the trading loop.
Failures degrade to a disabled sink (logged once).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from goldbot.core.config import GoldBotSettings
from goldbot.core.instruments import PRIMARY_INSTRUMENT
from goldbot.database.models import (
    Base,
    CompletedTrade,
    Order,
    OrderEvent,
    SystemEvent,
    TradeProposal,
)
from goldbot.database.session import make_engine, make_session_factory

logger = logging.getLogger("goldbot.database.repository")


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO timestamp; fall back to *now* on failure."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


class DatabaseSink:
    """Persists engine events into the relational schema."""

    def __init__(self, session_factory: sessionmaker, unsubscribe=None):
        self.session_factory = session_factory
        self._unsubscribe = unsubscribe
        self.disabled = False
        self.rows_written = 0

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @classmethod
    def from_settings(cls, settings: GoldBotSettings) -> "DatabaseSink | None":
        """Build a sink when a database URL is configured, else ``None``."""
        url = settings.database_url
        if not url:
            return None
        try:
            engine = make_engine(url)
            with engine.connect():
                pass  # verify connectivity once at startup
        except Exception as exc:
            logger.warning("Database sink disabled (connect failed: %s)", exc)
            return None
        factory = make_session_factory(engine)
        return cls(factory)

    # ------------------------------------------------------------------
    # Event entry point
    # ------------------------------------------------------------------

    def handle_event(self, event: dict) -> Any:
        """Subscriber callback for ``engine.subscribe``."""
        if self.disabled:
            return None
        handler = None
        try:
            raw_type = event.get("type") if isinstance(event, dict) else None
            event_type = raw_type if isinstance(raw_type, str) else None
            if event_type is not None:
                handler = {
                    "proposal": self._handle_proposal,
                    "order": self._handle_order,
                    "trade": self._handle_trade,
                    "risk": self._handle_risk,
                }.get(event_type)
            if handler is not None:
                handler(event.get("data") or {})
        except Exception:
            # A broken database must never take the trading loop down.
            self.disabled = True
            self.close()
            logger.exception("Database sink failed and is now disabled")
        return None

    # ------------------------------------------------------------------

    def _scope_rows(self, new_rows):
        session = self.session_factory()
        try:
            session.add_all(new_rows)
            session.commit()
            self.rows_written += len(new_rows)
        finally:
            session.close()

    def _handle_proposal(self, data: dict) -> None:
        created = _parse_dt(data.get("created_at"))
        symbol = data.get("symbol") or PRIMARY_INSTRUMENT.symbol
        direction = data.get("direction") or "long"
        entry_price = float(data.get("entry_price") or 0.0)
        row = TradeProposal(
            id=data.get("proposal_id"),
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=float(data.get("stop_loss") or 0.0),
            take_profit=float(data.get("take_profit") or 0.0),
            position_size=float(data.get("position_size") or 0.0),
            risk_pct=float(data.get("risk_pct") or 0.0),
            reason_text=data.get("reason_text"),
            confidence=data.get("confidence"),
            strategy_name=data.get("strategy_name"),
            timeframe=data.get("timeframe"),
            indicator_values=data.get("signal_snapshot"),
            market_trend=direction,
            proposal_expiry=created + timedelta(hours=1),
        )
        session = self.session_factory()
        try:
            # The schema enforces UNIQUE(symbol, entry_price, direction); a
            # replayed tape legitimately reproduces identical proposals, so
            # the mirrored row is replaced (latest state wins).
            from sqlalchemy import and_

            session.query(TradeProposal).filter(
                and_(
                    TradeProposal.symbol == symbol,
                    TradeProposal.direction == direction,
                    TradeProposal.entry_price == entry_price,
                )
            ).delete(synchronize_session=False)
            session.merge(row)
            session.commit()
            self.rows_written += 1
        finally:
            session.close()

    def _handle_order(self, data: dict) -> None:
        order_id = data.get("order_id")
        if not order_id:
            return
        fill_price = data.get("fill_price")
        order = Order(
            id=order_id,
            symbol=data.get("symbol") or PRIMARY_INSTRUMENT.symbol,
            side=data.get("side") or "buy",
            order_type="market",
            volume=float(data.get("volume") or 0.0),
            fill_price=float(fill_price) if fill_price else None,
            filled_volume=float(data.get("volume") or 0.0),
            remaining_volume=0.0,
            status="filled",
        )
        event = OrderEvent(
            order_id=order_id,
            event_type="fill",
            event_detail={"proposal_id": data.get("proposal_id")},
            price=float(fill_price) if fill_price else None,
            volume=float(data.get("volume") or 0.0),
        )
        self._scope_rows([order, event])

    def _handle_trade(self, data: dict) -> None:
        entry_time = _parse_dt(data.get("entry_time"))
        exit_time = _parse_dt(data.get("close_time"))
        pnl = float(data.get("pnl") or 0.0)
        row = CompletedTrade(
            symbol=data.get("symbol") or PRIMARY_INSTRUMENT.symbol,
            direction=data.get("side") or "buy",
            entry_price=float(data.get("entry_price") or 0.0),
            exit_price=float(data.get("close_price") or 0.0),
            volume=float(data.get("volume") or 0.0),
            entry_time=entry_time,
            exit_time=exit_time,
            gross_pnl=pnl,
            net_pnl=pnl,
            exit_reason=data.get("reason"),
        )
        self._scope_rows([row])

    def _handle_risk(self, data: dict) -> None:
        if data.get("status") != "kill_switch_active":
            return
        row = SystemEvent(
            event_type="kill_switch",
            source="risk",
            event_detail={"reasons": data.get("kill_switch_reasons", [])},
            relevance="critical",
        )
        self._scope_rows([row])


def attach_sink(engine_obj, settings: GoldBotSettings) -> DatabaseSink | None:
    """Subscribe a :class:`DatabaseSink` to ``engine_obj`` events if enabled."""
    url = settings.database_url
    if not url:
        return None
    sink = DatabaseSink.from_settings(settings)
    if sink is None:
        return None
    unsubscribe = engine_obj.subscribe(sink.handle_event)
    sink._unsubscribe = unsubscribe
    logger.info(
        "Database sink attached for engine %s (url=%s)",
        engine_obj.symbol,
        url.split("@")[-1],  # never log credentials
    )
    return sink


def ensure_schema(engine_url: str) -> None:
    """Create tables idempotently (dev/test helper; production uses Alembic)."""
    from sqlalchemy import create_engine

    engine = create_engine(engine_url)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
