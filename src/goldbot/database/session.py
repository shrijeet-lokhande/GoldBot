"""SQLAlchemy engine/session helpers for GoldBot.

The database is optional: paper trading works fully without it (the paper
broker persists to a JSON ledger). When ``GOLD_DATABASE_URL`` (or
``database_url`` in settings) is configured, the repository component can
mirror engine state intoSQL tables.

Example:
    >>> from goldbot.database.session import make_engine, session_scope
    >>> engine = make_engine("sqlite+pysqlite:///:memory:")  # doctest: +SKIP
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("goldbot.database.session")

DEFAULT_POOL_PRE_PING = True


def make_engine(database_url: str, **kwargs) -> Engine:
    """Create a SQLAlchemy engine with sensible defaults.

    For SQLite the default URL override is transparent; for PostgreSQL
    ``pool_pre_ping`` avoids stale connections after a DB restart.
    """
    kwargs.setdefault("pool_pre_ping", DEFAULT_POOL_PRE_PING)
    return create_engine(database_url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    """Create a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on success, rolls back on error, and always closes the session.
    Exceptions propagate - callers decide how to handle failures.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Database transaction failed; rolled back")
        raise
    finally:
        session.close()


def safe_database_url(url: str | None) -> str:
    """Mask the password portion of a database URL for safe logging."""
    if not url or "://" not in url:
        return "unset"
    scheme, _, rest = url.partition("://")
    if "@" in rest:
        userinfo, _, hostpart = rest.rpartition("@")
        user, sep, _pw = userinfo.partition(":")
        return f"{scheme}://{user}{'***' if sep else ''}@{hostpart}"
    return url
