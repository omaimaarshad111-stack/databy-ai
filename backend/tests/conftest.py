import asyncio
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_db
from app.core.config import get_settings
from app.core.rate_limit import auth_rate_limiter
from app.database_targets.connection_manager import connection_manager
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def test_engine(tmp_path: Path):
    database_path = tmp_path / "test_application.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.attributes["database_url"] = database_url
    command.upgrade(alembic_config, "head")

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield engine
    engine.dispose()


@pytest.fixture
def test_session_factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def api_client(test_session_factory) -> Generator[Callable[..., httpx.Response], None, None]:
    auth_rate_limiter.clear()

    def override_get_db() -> Generator[Session, None, None]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    def request(method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def send_request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send_request())

    yield request
    app.dependency_overrides.clear()
    auth_rate_limiter.clear()


@pytest.fixture
def connection_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_upload_storage_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "max_sqlite_upload_size_bytes", 2 * 1024 * 1024)
    monkeypatch.setattr(settings, "database_connection_timeout_seconds", 1)
    monkeypatch.setattr(
        settings,
        "postgres_credentials_encryption_key",
        Fernet.generate_key().decode("ascii"),
    )
    yield settings
    connection_manager.dispose_all()


@pytest.fixture
def authenticated_client(api_client):
    register = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "connection-owner",
            "email": "connections@example.com",
            "password": "Strong-password-123",
        },
    )
    assert register.status_code == 201
    login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "connections@example.com",
            "password": "Strong-password-123",
        },
    )
    assert login.status_code == 200
    return {
        "client": api_client,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "user_id": UUID(register.json()["id"]),
    }
