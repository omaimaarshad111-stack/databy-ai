import ipaddress
from functools import lru_cache
import os
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEVELOPMENT_JWT_SECRET = "local-development-only-change-this-secret-before-deploying"


def _is_public_web_origin(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    hostname = parsed.hostname or ""
    if not hostname or hostname.lower() in {"localhost", "127.0.0.1"}:
        return False
    if hostname.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global and not address.is_private and not address.is_loopback


def _is_public_postgres_host(value: str) -> bool:
    host = value.strip().rstrip(".")
    if not host or host.lower() in {"localhost", "127.0.0.1"}:
        return False
    if host.endswith(".localhost"):
        return False
    if ":" in host and host.count(":") == 1:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        return bool(labels) and all(
            label and not label.startswith("-") and not label.endswith("-")
            for label in labels
        )
    return address.is_global and not address.is_private and not address.is_loopback


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "databy.ai API")
        self.app_env = os.getenv("APP_ENV", "development")
        self.api_prefix = os.getenv("API_PREFIX", "/api/v1")
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ]
        self.auth_rate_limit_window_seconds = int(
            os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
        )
        self.auth_login_rate_limit = int(os.getenv("AUTH_LOGIN_RATE_LIMIT", "10"))
        self.auth_register_rate_limit = int(os.getenv("AUTH_REGISTER_RATE_LIMIT", "5"))
        self.database_url = os.getenv(
            "DATABASE_URL",
            "sqlite:///./data/databy_ai.db",
        )
        self.jwt_secret_key = os.getenv("JWT_SECRET_KEY") or DEVELOPMENT_JWT_SECRET
        self.jwt_access_token_expire_minutes = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )
        upload_dir = Path(
            os.getenv("SQLITE_UPLOAD_STORAGE_DIR", str(BACKEND_DIR / "data" / "uploads"))
        )
        self.sqlite_upload_storage_dir = (
            upload_dir if upload_dir.is_absolute() else BACKEND_DIR / upload_dir
        )
        self.max_sqlite_upload_size_bytes = int(
            os.getenv("MAX_SQLITE_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024))
        )
        self.database_connection_timeout_seconds = int(
            os.getenv("DATABASE_CONNECTION_TIMEOUT_SECONDS", "5")
        )
        self.postgres_credentials_encryption_key = os.getenv(
            "POSTGRES_CREDENTIALS_ENCRYPTION_KEY", ""
        )
        self.postgres_allowed_hosts = [
            host.strip()
            for host in os.getenv("POSTGRES_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        ]
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.groq_timeout_seconds = int(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))
        self.sql_generation_max_attempts = int(
            os.getenv("SQL_GENERATION_MAX_ATTEMPTS", "2")
        )
        self.sql_generation_max_question_chars = int(
            os.getenv("SQL_GENERATION_MAX_QUESTION_CHARS", "2000")
        )
        self.sql_generation_max_schema_chars = int(
            os.getenv("SQL_GENERATION_MAX_SCHEMA_CHARS", "24000")
        )
        self.sql_max_query_chars = int(os.getenv("SQL_MAX_QUERY_CHARS", "10000"))
        self.sql_execution_timeout_seconds = float(
            os.getenv("SQL_EXECUTION_TIMEOUT_SECONDS", "5")
        )
        self.sql_execution_default_page_size = int(
            os.getenv("SQL_EXECUTION_DEFAULT_PAGE_SIZE", "100")
        )
        self.sql_execution_max_page_size = int(
            os.getenv("SQL_EXECUTION_MAX_PAGE_SIZE", "500")
        )
        self.sql_execution_max_offset = int(
            os.getenv("SQL_EXECUTION_MAX_OFFSET", "100000")
        )
        self.sql_execution_max_columns = int(
            os.getenv("SQL_EXECUTION_MAX_COLUMNS", "100")
        )
        self.sql_execution_max_result_bytes = int(
            os.getenv("SQL_EXECUTION_MAX_RESULT_BYTES", str(2 * 1024 * 1024))
        )
        self.sql_execution_max_concurrent_per_user = int(
            os.getenv("SQL_EXECUTION_MAX_CONCURRENT_PER_USER", "2")
        )
        self.sql_execution_result_cache_ttl_seconds = int(
            os.getenv("SQL_EXECUTION_RESULT_CACHE_TTL_SECONDS", "900")
        )
        self.sql_execution_result_cache_max_bytes = int(
            os.getenv("SQL_EXECUTION_RESULT_CACHE_MAX_BYTES", str(32 * 1024 * 1024))
        )
        self.sql_execution_result_cache_max_entries = int(
            os.getenv("SQL_EXECUTION_RESULT_CACHE_MAX_ENTRIES", "500")
        )

    def resolved_database_url(self) -> str:
        from sqlalchemy.engine import make_url

        url = make_url(self.database_url)
        if url.get_backend_name() != "sqlite":
            raise ValueError("The internal application database must use SQLite.")
        database = url.database
        if database and database != ":memory:" and not Path(database).is_absolute():
            url = url.set(database=str((BACKEND_DIR / database).resolve()))
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env.lower() not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be development, test, or production.")
    if settings.jwt_access_token_expire_minutes <= 0:
        raise ValueError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive.")
    if settings.max_sqlite_upload_size_bytes <= 0:
        raise ValueError("MAX_SQLITE_UPLOAD_SIZE_BYTES must be positive.")
    if settings.database_connection_timeout_seconds <= 0:
        raise ValueError("DATABASE_CONNECTION_TIMEOUT_SECONDS must be positive.")
    if settings.groq_timeout_seconds <= 0:
        raise ValueError("GROQ_TIMEOUT_SECONDS must be positive.")
    if settings.sql_generation_max_attempts < 1:
        raise ValueError("SQL_GENERATION_MAX_ATTEMPTS must be positive.")
    if min(
        settings.sql_generation_max_question_chars,
        settings.sql_generation_max_schema_chars,
        settings.sql_max_query_chars,
    ) <= 0:
        raise ValueError("SQL generation and validation limits must be positive.")
    if settings.sql_execution_timeout_seconds <= 0:
        raise ValueError("SQL_EXECUTION_TIMEOUT_SECONDS must be positive.")
    if min(
        settings.sql_execution_default_page_size,
        settings.sql_execution_max_page_size,
        settings.sql_execution_max_columns,
        settings.sql_execution_max_concurrent_per_user,
        settings.sql_execution_result_cache_ttl_seconds,
        settings.sql_execution_result_cache_max_bytes,
        settings.sql_execution_result_cache_max_entries,
    ) <= 0:
        raise ValueError("SQL execution limits must be positive.")
    if settings.sql_execution_max_result_bytes < 1024:
        raise ValueError("SQL_EXECUTION_MAX_RESULT_BYTES must be at least 1024.")
    if settings.sql_execution_default_page_size > settings.sql_execution_max_page_size:
        raise ValueError(
            "SQL_EXECUTION_DEFAULT_PAGE_SIZE cannot exceed SQL_EXECUTION_MAX_PAGE_SIZE."
        )
    if settings.sql_execution_max_offset < 0:
        raise ValueError("SQL_EXECUTION_MAX_OFFSET cannot be negative.")
    if min(
        settings.auth_rate_limit_window_seconds,
        settings.auth_login_rate_limit,
        settings.auth_register_rate_limit,
    ) <= 0:
        raise ValueError("Authentication rate limits must be positive.")
    if len(settings.jwt_secret_key) < 32:
        raise ValueError("JWT_SECRET_KEY must contain at least 32 characters.")
    if any(
        host == "*"
        or any(character in host for character in "/\\@?#")
        or any(character.isspace() for character in host)
        for host in settings.postgres_allowed_hosts
    ):
        raise ValueError("POSTGRES_ALLOWED_HOSTS must contain exact hostnames or IPs.")
    if any(not _is_public_postgres_host(host) for host in settings.postgres_allowed_hosts):
        raise ValueError(
            "POSTGRES_ALLOWED_HOSTS must contain only public, non-local PostgreSQL hosts."
        )
    if settings.app_env.lower() == "production":
        if settings.jwt_secret_key == DEVELOPMENT_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be configured in production.")
        if "CORS_ORIGINS" not in os.environ:
            raise ValueError("CORS_ORIGINS must be explicitly configured in production.")
        if any(
            origin == "*"
            or not _is_public_web_origin(origin)
            or urlparse(origin).path not in ("", "/")
            for origin in settings.cors_origins
        ):
            raise ValueError(
                "Production CORS origins must be explicit public HTTPS origins without localhost/private addresses."
            )
        if not settings.postgres_credentials_encryption_key:
            raise ValueError(
                "POSTGRES_CREDENTIALS_ENCRYPTION_KEY must be configured in production."
            )
        if not settings.postgres_allowed_hosts:
            raise ValueError(
                "POSTGRES_ALLOWED_HOSTS must contain approved PostgreSQL hosts in production."
            )
        if any(not _is_public_postgres_host(host) for host in settings.postgres_allowed_hosts):
            raise ValueError(
                "POSTGRES_ALLOWED_HOSTS must contain only public, non-local PostgreSQL hosts."
            )
        try:
            Fernet(settings.postgres_credentials_encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise ValueError(
                "POSTGRES_CREDENTIALS_ENCRYPTION_KEY must be a valid Fernet key."
            ) from None
    return settings
