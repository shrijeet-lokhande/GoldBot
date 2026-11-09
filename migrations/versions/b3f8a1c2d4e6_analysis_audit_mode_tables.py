"""analysis, audit, account connections, mode changes, backtest results

Revision ID: b3f8a1c2d4e6
Revises: 0cbdf466ded8
Create Date: 2026-11-09 23:30:00.000000

Additive only: creates five new tables; no existing tables or data are
touched, so migrations never delete user or trading data.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f8a1c2d4e6"
down_revision: Union[str, None] = "0cbdf466ded8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_regime", sa.String(length=32), nullable=False),
        sa.Column("directional_bias", sa.String(length=16), nullable=False),
        sa.Column("htf_trend", sa.String(length=32), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_reports_symbol_time", "analysis_reports",
        ["symbol", "generated_at"], unique=False,
    )
    op.create_index("ix_analysis_reports_symbol", "analysis_reports", ["symbol"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_event", "audit_events", ["event"], unique=False)
    op.create_index("ix_audit_events_time", "audit_events", ["created_at"], unique=False)

    op.create_table(
        "account_connections",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("account_label", sa.String(length=64), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=False),
        sa.Column("authorized_live", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_connections_provider", "account_connections",
                    ["provider", "environment"], unique=False)
    op.create_index("ix_account_connections_provider_only", "account_connections",
                    ["provider"], unique=False)

    op.create_table(
        "trading_mode_changes",
        sa.Column("from_mode", sa.String(length=16), nullable=False),
        sa.Column("to_mode", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_mode_changes_time", "trading_mode_changes",
                    ["created_at"], unique=False)

    op.create_table(
        "backtest_results",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("start_bar", sa.Integer(), nullable=True),
        sa.Column("end_bar", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_results_symbol", "backtest_results", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_table("backtest_results")
    op.drop_table("trading_mode_changes")
    op.drop_table("account_connections")
    op.drop_table("audit_events")
    op.drop_table("analysis_reports")
