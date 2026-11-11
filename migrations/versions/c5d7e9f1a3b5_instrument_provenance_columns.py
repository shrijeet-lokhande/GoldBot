"""instrument provenance columns on market/order/position/trade tables

Revision ID: c5d7e9f1a3b5
Revises: b3f8a1c2d4e6
Create Date: 2026-11-11 00:00:00.000000

Additive only: adds a nullable `instrument` column to the four tables that
store instrument-scoped records and backfills it from the existing `symbol`
column. IMPORTANT provenance note: the `symbol` column is left untouched —
historical rows keep the instrument identifier they were actually recorded
under. The backfill records provenance (instrument = the symbol the row was
stored with), it never relabels data as something it was not. New rows will
populate `instrument` from the centralized instrument configuration while
`symbol` retains provider-specific mapping context.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d7e9f1a3b5"
down_revision: Union[str, None] = "b3f8a1c2d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("market_bars", "orders", "positions", "completed_trades")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("instrument", sa.String(length=32), nullable=True))
        # Provenance backfill: copy the row's own stored symbol. No relabeling.
        op.execute(f"UPDATE {table} SET instrument = symbol")


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "instrument")
