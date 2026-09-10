"""Regression coverage for the local dashboard bootstrap and migrations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect, select

from modules import entitlements
from modules.db import session_scope
from modules.models import Business, BusinessModule, ConversationSession
from modules.tenancy import LEGACY_BUSINESS_ID, ensure_legacy_business
from scripts.seed_local_demo import _ensure_client_business, _seed_activity


def test_legacy_demo_has_demo_settings_and_default_modules(demo_app):
    db = session_scope()
    try:
        business = db.get(Business, LEGACY_BUSINESS_ID)
        assert business is not None
        assert business.settings["intake"]["selection_mode"] == "menu"
        assert business.settings["intake"]["demo_disclaimer"] is True
        assert entitlements.enabled_module_keys(db, business.id) == set(
            entitlements.DEFAULT_ENABLED_MODULES
        )
    finally:
        db.close()


def test_legacy_demo_repairs_empty_sqlite_bootstrap(demo_app):
    db = session_scope()
    try:
        business = db.get(Business, LEGACY_BUSINESS_ID)
        business.settings = {}
        db.execute(
            BusinessModule.__table__.delete().where(
                BusinessModule.business_id == LEGACY_BUSINESS_ID
            )
        )
        db.commit()

        repaired = ensure_legacy_business(db)
        assert repaired.settings["intake"]["demo_disclaimer"] is True
        modules = set(
            db.execute(
                select(BusinessModule.module_key).where(
                    BusinessModule.business_id == LEGACY_BUSINESS_ID
                )
            ).scalars()
        )
        assert modules == set(entitlements.DEFAULT_ENABLED_MODULES)
    finally:
        db.close()


def test_local_activity_seed_adds_conversations_idempotently(demo_app):
    db = session_scope()
    try:
        business = _ensure_client_business(db)
        first = _seed_activity(db, business_id=business.id)
        db.commit()
        second = _seed_activity(db, business_id=business.id)
        db.commit()

        sessions = list(
            db.execute(
                select(ConversationSession).where(
                    ConversationSession.business_id == business.id
                )
            ).scalars()
        )
    finally:
        db.close()

    assert first == (5, 2, 3)
    assert second == (0, 0, 0)
    assert len(sessions) == 3


def test_sqlite_alembic_upgrade_reaches_head(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.db"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path}",
            "FLASK_ENV": "development",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repository_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    import sqlalchemy as sa

    engine = sa.create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"businesses", "business_modules", "platform_users", "user_sessions"} <= tables

    with engine.connect() as connection:
        business = connection.execute(
            sa.text("SELECT settings FROM businesses WHERE id = :id"),
            {"id": LEGACY_BUSINESS_ID},
        ).scalar_one()
    assert '"demo_disclaimer": true' in business.lower()


def test_postgres_offline_migration_sql_renders(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    sql_path = tmp_path / "upgrade.sql"
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://user:password@localhost/ntx"

    with sql_path.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
            cwd=repository_root,
            env=env,
            stdout=output,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stderr
    rendered = sql_path.read_text(encoding="utf-8")
    assert "json_build_object" in rendered
    assert "CREATE TABLE business_modules" in rendered
