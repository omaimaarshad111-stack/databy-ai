from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DatabaseConnection
from app.db.session import get_db


def test_migrations_create_all_application_tables(test_engine) -> None:
    assert set(inspect(test_engine).get_table_names()) == {
        "alembic_version",
        "approvals",
        "audit_logs",
        "conversations",
        "database_connections",
        "messages",
        "query_history",
        "saved_queries",
        "users",
    }


def test_sqlite_foreign_key_enforcement_is_enabled(test_engine) -> None:
    with test_engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_foreign_key_constraint_rejects_unknown_connection(test_session_factory) -> None:
    with test_session_factory() as session:
        session.add(
            DatabaseConnection(
                user_id=uuid4(),
                name="unknown owner",
                database_type="sqlite",
                connection_metadata={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_dependency_closes_session() -> None:
    class SessionContext:
        exited = False

        def __enter__(self):
            return Session()

        def __exit__(self, *_: object) -> None:
            self.exited = True

    context = SessionContext()
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(session_factory=lambda: context)),
        }
    )
    dependency = get_db(request)

    next(dependency)
    dependency.close()

    assert context.exited


def test_test_database_is_not_the_development_database(test_engine) -> None:
    database = Path(str(test_engine.url.database)).resolve()
    development_database = (
        Path(__file__).resolve().parents[2] / "data" / "databy_ai.db"
    ).resolve()

    assert database != development_database
