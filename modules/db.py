"""
db.py
SQLAlchemy engine/session setup.

DATABASE_URL drives everything:
  - postgres(ql)://...  -> normalized to the psycopg driver and used as-is.
  - sqlite:///...        -> allowed only for local development and tests.
  - unset                -> defaults to a local SQLite file (dev/test only;
                            never rely on this on Render, where a disk is
                            ephemeral across deploys).
"""

import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _normalize_database_url(raw: str) -> str:
    # Render (and Heroku-style providers) sometimes hand out
    # "postgres://" URLs; SQLAlchemy 2.x + psycopg needs "postgresql+psycopg://".
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://") and "+psycopg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def get_database_url() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        logger.warning(
            "[db] DATABASE_URL not set — defaulting to local SQLite file "
            "'sms_intake_dev.db'. This is fine for local dev/tests only; "
            "set DATABASE_URL to Postgres in every deployed environment."
        )
        return "sqlite:///sms_intake_dev.db"
    return _normalize_database_url(raw)


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite:")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {"check_same_thread": False} if is_sqlite(url) else {}
        _engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True, future=True)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def init_db() -> None:
    """
    Creates all tables if they don't exist yet.

    Used for local dev/tests (SQLite) and as a safety net. Production
    Postgres deployments should run `alembic upgrade head` explicitly
    (see migrations/) rather than relying solely on create_all.
    """
    import modules.models  # noqa: F401  (ensure models are registered on Base)
    Base.metadata.create_all(bind=get_engine())


def session_scope():
    """Context manager yielding a SQLAlchemy session that commits/rolls back."""
    factory = get_session_factory()
    return factory()
