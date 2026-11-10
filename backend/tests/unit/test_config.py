import pytest
from cryptography.fernet import Fernet

from app.core.config import DEVELOPMENT_JWT_SECRET, get_settings


def test_production_requires_explicit_jwt_secret_and_https_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", DEVELOPMENT_JWT_SECRET)
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv(
        "POSTGRES_CREDENTIALS_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setenv("POSTGRES_ALLOWED_HOSTS", "db.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            get_settings()

        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 48)
        with pytest.raises(ValueError, match="HTTPS"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_requires_valid_credential_encryption_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("CORS_ORIGINS", "")
    monkeypatch.setenv("POSTGRES_CREDENTIALS_ENCRYPTION_KEY", "")
    monkeypatch.setenv("POSTGRES_ALLOWED_HOSTS", "db.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="POSTGRES_CREDENTIALS_ENCRYPTION_KEY"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_localhost_in_public_origins_and_db_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("CORS_ORIGINS", "https://localhost:5173")
    monkeypatch.setenv(
        "POSTGRES_CREDENTIALS_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setenv("POSTGRES_ALLOWED_HOSTS", "db.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="public HTTPS origins"):
            get_settings()
    finally:
        get_settings.cache_clear()

    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("POSTGRES_ALLOWED_HOSTS", "localhost")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="public.*PostgreSQL hosts"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_readiness_endpoint_checks_application_database(api_client) -> None:
    response = api_client("GET", "/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "databy.ai"}
