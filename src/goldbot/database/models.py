"""GoldBot database models - SQLAlchemy ORM models for all application state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every GoldBot table."""


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SignalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class EventType(str, Enum):
    SIGNAL = "signal"
    PROPOSAL = "proposal"
    APPROVAL = "approval"
    ORDER = "order"
    FILL = "fill"
    POSITION_OPEN = "position_open"
    POSITION_CLOSE = "position_close"
    RISK_LIMIT = "risk_limit"
    KILL_SWITCH = "kill_switch"
    CONFIG_CHANGE = "config_change"


class UUIDMixin:
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MarketBar(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "market_bars"

    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    bid = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    source = Column(String(64), nullable=True)
    is_complete = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_market_bars_symbol_tf", "symbol", "timeframe"),
        Index("ix_market_bars_symbol_tf_timestamp", "symbol", "timeframe", "created_at"),
    )


class MarketQuote(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "market_quotes"

    symbol = Column(String(32), nullable=False, index=True)
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    spread = Column(Float, nullable=False)
    mid_price = Column(Float, nullable=True)
    source = Column(String(64), nullable=True)


class InstrumentMetadata(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "instrument_metadata"

    symbol = Column(String(32), nullable=False, unique=True, index=True)
    venue = Column(String(64), nullable=True)
    asset_type = Column(String(32), nullable=True)
    contract_size = Column(Float, nullable=True)
    tick_size = Column(Float, nullable=True)
    tick_value = Column(Float, nullable=True)
    volume_step = Column(Float, nullable=True)
    min_volume = Column(Float, nullable=True)
    max_volume = Column(Float, nullable=True)
    margin_rate = Column(Float, nullable=True)
    commission = Column(Float, nullable=True)
    swap_long = Column(Float, nullable=True)
    swap_short = Column(Float, nullable=True)
    verified = Column(Boolean, default=False, nullable=False)
    source = Column(String(64), nullable=True)


class StrategySignal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "strategy_signals"

    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(16), nullable=False)
    timeframe = Column(String(16), nullable=False)
    reference_price = Column(Float, nullable=False)
    stop_distance = Column(Float, nullable=False)
    take_profit_multiple = Column(Float, nullable=False)
    reason_codes = Column(JSON, nullable=True, default=list)
    indicator_snapshot = Column(JSON, nullable=True)
    strategy_version = Column(String(32), nullable=True, default="1.0.0")

    __table_args__ = (
        Index("ix_strategy_signals_symbol", "symbol"),
        Index("ix_strategy_signals_created", "created_at"),
    )


class TradeProposal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "trade_proposals"

    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(16), nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    risk_pct = Column(Float, nullable=False)
    reason_text = Column(Text, nullable=True)
    confidence = Column(String(16), nullable=True)
    strategy_name = Column(String(32), nullable=True)
    timeframe = Column(String(16), nullable=True)
    indicator_values = Column(JSON, nullable=True)
    market_trend = Column(String(16), nullable=True)
    rsi = Column(Float, nullable=True)
    ema_20 = Column(Float, nullable=True)
    ema_50 = Column(Float, nullable=True)
    ema_200 = Column(Float, nullable=True)
    adx = Column(Float, nullable=True)
    spread = Column(Float, nullable=True)
    proposal_expiry = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "entry_price", "direction", name="uq_proposal_key"),
        Index("ix_trade_proposals_expiry", "proposal_expiry"),
        Index("ix_trade_proposals_symbol", "symbol"),
    )


class ApprovalDecision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "approval_decisions"

    proposal_id = Column(String(36), nullable=False, index=True)
    approved_by = Column(String(128), nullable=True)
    decision = Column(String(16), nullable=False)
    decision_timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reason_text = Column(Text, nullable=True)
    risk_check_passed = Column(Boolean, nullable=False, default=False)
    market_price_at_decision = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_approval_decisions_proposal", "proposal_id"),
        Index("ix_approval_decisions_timestamp", "decision_timestamp"),
    )


class Order(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "orders"

    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(16), nullable=False)
    order_type = Column(String(16), nullable=False)
    volume = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    filled_volume = Column(Float, nullable=False, default=0.0)
    fill_price = Column(Float, nullable=True)
    remaining_volume = Column(Float, nullable=False)
    client_order_id = Column(String(64), nullable=True, unique=True)
    # Note: attribute cannot be called 'metadata' (reserved by Declarative);
    # the DB column keeps the name for API compatibility.
    order_metadata = Column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("ix_orders_symbol", "symbol"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_client_order_id", "client_order_id"),
    )


class OrderEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "order_events"

    order_id = Column(String(36), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    event_detail = Column(JSON, nullable=True)
    price = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_order_events_order", "order_id"),
        Index("ix_order_events_timestamp", "created_at"),
    )


class Position(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "positions"

    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(16), nullable=False)
    volume = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    unrealised_pnl = Column(Float, nullable=False, default=0.0)
    realised_pnl = Column(Float, nullable=False, default=0.0)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_reason = Column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_positions_symbol", "symbol"),
        Index("ix_positions_status", "opened_at"),
    )


class CompletedTrade(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "completed_trades"

    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(16), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=False)
    gross_pnl = Column(Float, nullable=False)
    net_pnl = Column(Float, nullable=False)
    commission = Column(Float, nullable=False, default=0.0)
    swap = Column(Float, nullable=False, default=0.0)
    exit_reason = Column(String(32), nullable=True)
    strategy = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_completed_trades_symbol", "symbol"),
        Index("ix_completed_trades_entry_time", "entry_time"),
        Index("ix_completed_trades_exit_time", "exit_time"),
    )


class AccountSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "account_snapshots"

    total_equity = Column(Float, nullable=False)
    free_margin = Column(Float, nullable=False)
    used_margin = Column(Float, nullable=False)
    unrealised_pnl = Column(Float, nullable=False, default=0.0)
    realised_pnl = Column(Float, nullable=False, default=0.0)
    free_cash = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_account_snapshots_timestamp", "timestamp"),)


class PerformanceMetrics(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "performance_metrics"

    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    gross_profit = Column(Float, nullable=False, default=0.0)
    gross_loss = Column(Float, nullable=False, default=0.0)
    net_profit = Column(Float, nullable=False, default=0.0)
    total_fees = Column(Float, nullable=False, default=0.0)
    total_swaps = Column(Float, nullable=False, default=0.0)
    max_drawdown = Column(Float, nullable=False, default=0.0)
    Sharpe_ratio = Column(Float, nullable=True)
    Sortino_ratio = Column(Float, nullable=True)
    expectancy = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True, default=1.0)
    average_win = Column(Float, nullable=True)
    average_loss = Column(Float, nullable=True)
    largest_win = Column(Float, nullable=True, default=0.0)
    largest_loss = Column(Float, nullable=True, default=0.0)
    win_rate = Column(Float, nullable=True)
    exposure_time_pct = Column(Float, nullable=True, default=0.0)
    long_total_pnl = Column(Float, nullable=True, default=0.0)
    short_total_pnl = Column(Float, nullable=True, default=0.0)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_performance_metrics_timestamp", "timestamp"),)


class BotConfiguration(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "bot_configuration"

    key = Column(String(64), nullable=False, unique=True, index=True)
    value = Column(JSON, nullable=False)
    description = Column(String(256), nullable=True)

    __table_args__ = (Index("ix_bot_configuration_key", "key"),)


class SystemEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "system_events"

    event_type = Column(String(32), nullable=False)
    source = Column(String(64), nullable=True)
    event_detail = Column(JSON, nullable=True)
    relevance = Column(String(32), nullable=True)


class AnalysisReportRow(Base, UUIDMixin, TimestampMixin):
    """Persisted output of the XAUUSD analysis engine."""

    __tablename__ = "analysis_reports"

    symbol = Column(String(32), nullable=False, index=True)
    market_regime = Column(String(32), nullable=False)
    directional_bias = Column(String(16), nullable=False)
    htf_trend = Column(String(32), nullable=True)
    confidence_score = Column(Integer, nullable=True)
    report = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_analysis_reports_symbol_time", "symbol", "generated_at"),)


class AuditEventRow(Base, UUIDMixin, TimestampMixin):
    """Append-only audit trail for mode changes and security-relevant actions."""

    __tablename__ = "audit_events"

    actor = Column(String(128), nullable=True)
    event = Column(String(64), nullable=False, index=True)
    details = Column(JSON, nullable=True)

    __table_args__ = (Index("ix_audit_events_time", "created_at"),)


class AccountConnection(Base, UUIDMixin, TimestampMixin):
    """Broker/account connection metadata. NEVER stores credentials or tokens."""

    __tablename__ = "account_connections"

    provider = Column(String(32), nullable=False, index=True)  # oanda | paper | ...
    environment = Column(String(16), nullable=False, default="practice")  # practice|live
    account_label = Column(String(64), nullable=True)
    external_account_id = Column(String(64), nullable=True)  # broker-side ID
    connected = Column(Boolean, default=False, nullable=False)
    authorized_live = Column(Boolean, default=False, nullable=False)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    # NOTE: no credential columns exist by design; tokens live in env/config.

    __table_args__ = (Index("ix_account_connections_provider", "provider", "environment"),)


class TradingModeChange(Base, UUIDMixin, TimestampMixin):
    """Audit record for every paper<->live trading-mode switch attempt."""

    __tablename__ = "trading_mode_changes"

    from_mode = Column(String(16), nullable=False)
    to_mode = Column(String(16), nullable=False)
    result = Column(String(16), nullable=False)  # ok | denied | already
    actor = Column(String(128), nullable=True)
    reason = Column(Text, nullable=True)

    __table_args__ = (Index("ix_trading_mode_changes_time", "created_at"),)


class BacktestResultRow(Base, UUIDMixin, TimestampMixin):
    """Persisted backtesting/walk-forward results."""

    __tablename__ = "backtest_results"

    symbol = Column(String(32), nullable=False, index=True)
    strategy_name = Column(String(64), nullable=False)
    timeframe = Column(String(16), nullable=False)
    start_bar = Column(Integer, nullable=True)
    end_bar = Column(Integer, nullable=True)
    params = Column(JSON, nullable=True)
    metrics = Column(JSON, nullable=False)

    __table_args__ = (Index("ix_backtest_results_symbol", "symbol"),)


__all__ = [
    "OrderStatus",
    "OrderType",
    "Side",
    "SignalDirection",
    "SignalStatus",
    "TradeStatus",
    "ApprovalStatus",
    "EventType",
    "MarketBar",
    "MarketQuote",
    "InstrumentMetadata",
    "StrategySignal",
    "TradeProposal",
    "ApprovalDecision",
    "Order",
    "OrderEvent",
    "Position",
    "CompletedTrade",
    "AccountSnapshot",
    "PerformanceMetrics",
    "BotConfiguration",
    "SystemEvent",
    "AnalysisReportRow",
    "AuditEventRow",
    "AccountConnection",
    "TradingModeChange",
    "BacktestResultRow",
]


def create_all_tables(database_url: str | None = None):
    """Create all database tables from the ORM metadata.

    Intended for tests and throwaway/dev databases only; production schema
    management goes through Alembic migrations.

    Args:
        database_url: SQLAlchemy URL. Falls back to the configured
            ``GOLD_DATABASE_URL``/settings value.
    """
    from sqlalchemy import create_engine

    if not database_url:
        from goldbot.core.config import load_settings

        database_url = load_settings().database_url
    if not database_url:
        raise ValueError(
            "No database URL configured (set GOLD_DATABASE_URL or pass database_url explicitly)"
        )
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
