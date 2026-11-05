"""Alembic environment for GoldBot.

Resolution order for the target database URL:
    1. ``GOLD_DATABASE_URL`` environment variable (matches the app config
       prefix), falling back to the generic ``DATABASE_URL``.
    2. ``sqlalchemy.url`` from ``alembic.ini`` (development only.

Run from the repository root:
    alembic upgrade head
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the src/ layout importable when alembic is invoked directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldbot.core.config import load_settings  # noqa: E402
from goldbot.database.models import Base  # noqa: E402
from goldbot.database.session import safe_database_url  # noqa: E402

# Alembic Config object; provides access to alembic.ini values.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate support.
target_metadata = Base.metadata

# --- URL resolution -------------------------------------------------------
db_url = os.environ.get("GOLD_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not db_url:
    try:
        settings = load_settings(ROOT / "config" / "settings.yaml")
        db_url = settings.database_url
    except Exception:
        db_url = None

if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
    print(f"Alembic target: {safe_database_url(db_url)}", flush=True)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
