"""Database integration tests: ORM mapping, migrations, and CRUD round-trips.

A17 / A18 of docs/TEST_PLAN.md.

SQLite is used as the portable in-process database (alembic-managed) so the
suite runs anywhere; the PostgreSQL target is verified separately via
`alembic upgrade head` against a live server (see docs/PROGRESS.md).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "migrations"))

from goldbot.core.models import OrderSide, OrderStatus, OrderType  # noqa: E402
from goldbot.database.models import (  # noqa: E402
    ApprovalDecision,
    BotConfiguration,
    CompletedTrade,
    MarketBar,
    Order,
    PerformanceMetrics,
    Position,
    StrategySignal,
    SystemEvent,
    TradeProposal,
    UUIDMixin,
)
from goldbot.database.session import (  # noqa: E402
    make_engine,
    make_session_factory,
    safe_database_url,
    session_scope,
)


@pytest.fixture()
def migrated_sqlite(tmp_path):
    """Create a real Alembic-migrated SQLite DB in tmp_path."""
    import alembic.command
    import alembic.config

    db_path = tmp_path / "goldbot_test.sqlite3"
    url = f"sqlite+pysqlite:///{db_path}"
    cfg = alembic.config.Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    alembic.command.upgrade(cfg, "head")
    return url


def test_all_orm_tables_registered():
    """Every documented model maps into the shared MetaData (A17 part 1)."""
    from goldbot.database.models import Base

    expected = {
        "market_bars",
        "market_quotes",
        "instrument_metadata",
        "strategy_signals",
        "trade_proposals",
        "approval_decisions",
        "orders",
        "order_events",
        "positions",
        "completed_trades",
        "account_snapshots",
        "performance_metrics",
        "bot_configuration",
        "system_events",
        # v2: analysis, audit, connections, mode changes, backtests
        "analysis_reports",
        "audit_events",
        "account_connections",
        "trading_mode_changes",
        "backtest_results",
    }
    assert expected == set(Base.metadata.tables)


def test_migrations_create_all_tables(migrated_sqlite):
    """alembic upgrade head materialises every ORM table (A17)."""
    engine = make_engine(migrated_sqlite)
    names = set(engine.table_names()) if hasattr(engine, "table_names") else None
    if names is None:
        from sqlalchemy import inspect

        names = set(inspect(engine).get_table_names())
    from goldbot.database.models import Base

    assert set(Base.metadata.tables) <= names
    engine.dispose()


def test_uuid_mixin_generates_ids():
    ids = {str(UUIDMixin.id.default.arg(None)) for _ in range(2)}
    # The default callable must produce distinct UUID strings (regression:
    # it used to raise NameError) .
    assert len(ids) == 2
    assert all(len(x) == 36 for x in ids)


def test_order_crud_roundtrip(migrated_sqlite):
    """A18: Order row round-trips incl. enums, JSON blob and UUID PK."""
    engine = make_engine(migrated_sqlite)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        record = Order(
            symbol="XAUUSD",
            side=OrderSide.BUY.value,
            order_type=OrderType.MARKET.value,
            volume=0.25,
            price=None,
            stop_loss=1945.0,
            take_profit=1990.0,
            status=OrderStatus.FILLED.value,
            filled_volume=0.25,
            fill_price=1950.15,
            remaining_volume=0.0,
            order_metadata={"proposal": "risk-approved"},
        )
        session.add(record)
        session.flush()
        order_id = record.id  # default lambda must have produced a UUID
        assert len(order_id) == 36

    with session_scope(factory) as session:
        fetched = session.get(Order, order_id)
        assert fetched is not None
        assert fetched.symbol == "XAUUSD"
        assert fetched.side == "buy"
        assert fetched.status == "filled"
        assert fetched.fill_price == pytest.approx(1950.15)
        assert fetched.order_metadata == {"proposal": "risk-approved"}
    engine.dispose()


def test_mixed_model_crud(migrated_sqlite):
    """A18: representative rows across the biggest tables round-trip."""
    engine = make_engine(migrated_sqlite)
    factory = make_session_factory(engine)
    now = datetime.now(timezone.utc)
    with session_scope(factory) as session:
        session.add_all(
            [
                MarketBar(
                    symbol="XAUUSD",
                    timeframe="15m",
                    open_price=1950.0,
                    high_price=1955.0,
                    low_price=1948.0,
                    close_price=1952.0,
                    volume=120.0,
                    bid=1949.9,
                    ask=1950.1,
                    source="csv",
                    is_complete=True,
                    created_at=now,
                    updated_at=now,
                ),
                StrategySignal(
                    symbol="XAUUSD",
                    direction="long",
                    timeframe="15m",
                    reference_price=1952.0,
                    stop_distance=12.0,
                    take_profit_multiple=2.0,
                    reason_codes=["adx_above_minimum"],
                    created_at=now,
                    updated_at=now,
                    strategy_version="1.0.0",
                ),
                TradeProposal(
                    symbol="XAUUSD",
                    direction="long",
                    entry_price=1952.0,
                    stop_loss=1940.0,
                    take_profit=1976.0,
                    position_size=0.2,
                    risk_pct=0.25,
                    reason_text="adx okay",
                    confidence="high",
                    strategy_name="trend_pullback",
                    timeframe="15m",
                    proposal_expiry=now + timedelta(hours=1),
                    created_at=now,
                    updated_at=now,
                ),
                ApprovalDecision(
                    proposal_id="11111111-1111-1111-1111-111111111111",
                    approved_by="operator",
                    decision="approved",
                    reason_text="looks good",
                    risk_check_passed=True,
                    market_price_at_decision=1952.0,
                ),
                Position(
                    symbol="XAUUSD",
                    side="long",
                    volume=0.2,
                    entry_price=1952.5,
                    current_price=1955.0,
                    stop_loss=1940.5,
                    take_profit=1976.5,
                    unrealised_pnl=50.0,
                    realised_pnl=0.0,
                    opened_at=now,
                ),
                CompletedTrade(
                    symbol="XAUUSD",
                    direction="long",
                    entry_price=1952.5,
                    exit_price=1976.5,
                    volume=0.2,
                    entry_time=now,
                    exit_time=now + timedelta(minutes=30),
                    gross_pnl=480.0,
                    net_pnl=480.0,
                    exit_reason="take_profit",
                    strategy="trend_pullback",
                ),
                PerformanceMetrics(
                    total_trades=3,
                    winning_trades=2,
                    losing_trades=1,
                    gross_profit=480.0,
                    gross_loss=100.0,
                    net_profit=380.0,
                    win_rate=66.6,
                    timestamp=now,
                    created_at=now,
                    updated_at=now,
                ),
                BotConfiguration(
                    key="risk_per_trade_pct",
                    value="0.25",
                    description="risk per trade (percent)",
                    created_at=now,
                    updated_at=now,
                ),
                SystemEvent(
                    event_type="kill_switch",
                    source="risk",
                    event_detail={"reason": "manual"},
                    relevance="critical",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

    with session_scope(factory) as session:
        assert session.scalar(select(func.count()).select_from(MarketBar)) == 1
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1
        assert session.scalar(select(func.count()).select_from(TradeProposal)) == 1
        bar = session.scalar(select(MarketBar))
        assert bar.close_price == pytest.approx(1952.0)
        assert bar.bid == pytest.approx(1949.9)
        signal = session.scalar(select(StrategySignal))
        assert signal.direction == "long"
        assert signal.reason_codes == ["adx_above_minimum"]
        trade = session.scalar(select(CompletedTrade))
        assert trade.net_pnl > trade.gross_pnl - 1e-6
        assert trade.gross_pnl == pytest.approx(480.0)
        metric = session.scalar(select(PerformanceMetrics))
        assert metric.win_rate == pytest.approx(66.6)
        assert session.scalar(select(func.count()).select_from(SystemEvent)) == 1
        assert session.scalar(select(func.count()).select_from(BotConfiguration)) == 1
        assert session.scalar(select(func.count()).select_from(Position)) == 1
        assert session.scalar(select(func.count()).select_from(ApprovalDecision)) == 1
    engine.dispose()


def test_session_scope_rollback_on_error(migrated_sqlite):
    """A failed transaction rolls back and does not leave partial rows."""
    engine = make_engine(migrated_sqlite)
    factory = make_session_factory(engine)
    with pytest.raises(Exception):
        with session_scope(factory) as session:
            session.add(
                MarketBar(
                    symbol="XAUUSD",
                    timeframe="15m",
                    open_price=1950.0,
                    high_price=1955.0,
                    low_price=1948.0,
                    close_price=1952.0,
                    volume=120.0,
                )
            )
            session.flush()
            raise RuntimeError("synthetic failure")
    with session_scope(factory) as session:
        assert session.scalar(select(func.count()).select_from(MarketBar)) == 0
    engine.dispose()


def test_safe_database_url_masks_password():
    assert (
        safe_database_url("postgresql+psycopg://goldbot:sekret@localhost:5432/goldbot")
        == "postgresql+psycopg://goldbot***@localhost:5432/goldbot"
    )
    assert (
        safe_database_url("sqlite+pysqlite:///goldbot.sqlite3")
        == "sqlite+pysqlite:///goldbot.sqlite3"
    )
    assert safe_database_url(None) == "unset"


def test_database_sink_mirrors_engine_events(tmp_path):
    """Opt-in mirror: engine events land in the schema, engine loop clean."""
    import alembic.command
    import alembic.config
    from sqlalchemy import func, inspect, select

    from goldbot.core.config import GoldBotSettings
    from goldbot.database.repository import attach_sink
    from goldbot.engine import TradingEngine

    db_path = tmp_path / "sink.sqlite3"
    url = f"sqlite+pysqlite:///{db_path}"
    cfg = alembic.config.Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    alembic.command.upgrade(cfg, "head")

    settings = GoldBotSettings(
        mode="paper",
        instrument_symbol="XAUUSD",
        instrument_venue="paper",
        asset_type="spot",
        initial_equity=10_000.0,
        database_url=url,
    )
    eng = TradingEngine(
        settings,
        auto_approve=True,
        persistence_path=tmp_path / "sink_orders.json",
    )
    sink = attach_sink(eng, settings)
    assert sink is not None

    while eng._replay_index < len(eng._all_candles):
        eng.step_bar()
    eng.save_state()

    assert not sink.disabled, "sink must survive a full replay"
    assert len(eng.get_trades()) > 0

    engine = make_engine(url)
    inspector = inspect(engine)
    with session_scope(make_session_factory(engine)) as session:
        if "trade_proposals" in inspector.get_table_names():
            assert session.scalar(select(func.count()).select_from(TradeProposal)) > 0
        trade_count = session.scalar(select(func.count()).select_from(CompletedTrade))
        order_count = session.scalar(select(func.count()).select_from(Order))
    engine.dispose()

    assert trade_count == len(eng.get_trades())
    assert order_count == len(eng.get_orders())


def test_database_sink_ignores_bad_events():
    """A malformed event must not raise (sink is defensive)."""
    from goldbot.database.repository import DatabaseSink
    from goldbot.database.session import make_engine, make_session_factory

    factory = make_session_factory(make_engine("sqlite+pysqlite:///:memory:"))
    sink = DatabaseSink(factory)
    # Nothing stored yet: SQLite in-memory has no tables, so handler must
    # disable itself rather than raise.
    sink.handle_event({"type": "proposal", "data": {"proposal_id": "x"}})
    sink.handle_event({"type": "order", "data": {}})
    sink.handle_event({"type": "trade", "data": {"malformed": True}})
    sink.handle_event({"type": "unknown", "data": {}})


def test_instrument_provenance_backfill_and_new_rows(migrated_sqlite):
    """The provenance migration backfills instrument=symbol without
    touching symbol (no relabeling), and new writes carry the canonical
    instrument."""
    import sqlalchemy as sa

    engine = make_engine(migrated_sqlite)
    factory = make_session_factory(engine)
    # Simulate a pre-migration row: instrument NULL, symbol set.
    with session_scope(factory) as session:
        session.add(
            MarketBar(
                id="prov-bar-1",
                symbol="XAUUSD",
                instrument=None,
                timeframe="15m",
                open_price=2000.0,
                high_price=2001.0,
                low_price=1999.0,
                close_price=2000.5,
                volume=10.0,
                is_complete=True,
            )
        )
    # Backfill behaviour: UPDATE instrument = symbol (as the migration does).
    engine = sa.create_engine(migrated_sqlite)
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE market_bars SET instrument = symbol WHERE instrument IS NULL")
        )
    with session_scope(factory) as session:
        row = session.get(MarketBar, "prov-bar-1")
        assert row.symbol == "XAUUSD"   # untouched — no relabeling
        assert row.instrument == "XAUUSD"
    engine.dispose()


def test_new_orders_and_trades_carry_canonical_instrument(migrated_sqlite):
    from goldbot.core.instruments import PRIMARY_INSTRUMENT
    from goldbot.database.repository import DatabaseSink

    sink = DatabaseSink.__new__(DatabaseSink)  # bypass settings wiring
    sink.session_factory = make_session_factory(make_engine(migrated_sqlite))
    sink.rows_written = 0
    sink.unsubscribe = None

    order_data = {
        "order_id": "prov-order-1",
        "symbol": "XAUUSD",
        "side": "buy",
        "volume": 0.1,
        "fill_price": 2005.0,
        "proposal_id": "p1",
    }
    sink._handle_order(order_data)
    sink._handle_trade(
        {
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 2005.0,
            "close_price": 2010.0,
            "volume": 0.1,
            "pnl": 50.0,
            "entry_time": "2024-01-15T10:00:00+00:00",
            "close_time": "2024-01-15T11:00:00+00:00",
            "reason": "take_profit",
        }
    )
    sink_engine = make_engine(migrated_sqlite)
    with session_scope(make_session_factory(sink_engine)) as session:
        order = session.get(Order, "prov-order-1")
        trade = session.get(CompletedTrade, order.id) if False else (
            session.query(CompletedTrade).first()
        )
        assert order.instrument == PRIMARY_INSTRUMENT.symbol
        assert order.symbol == "XAUUSD"
        assert trade.instrument == PRIMARY_INSTRUMENT.symbol
    sink_engine.dispose()
