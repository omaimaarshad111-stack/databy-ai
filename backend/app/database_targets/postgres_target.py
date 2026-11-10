from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.database_targets.exceptions import (
    CredentialEncryptionError,
    TargetConnectionError,
)
from app.database_targets.network_policy import resolve_public_postgres_address


def _fernet() -> Fernet:
    key = get_settings().postgres_credentials_encryption_key
    if not key:
        raise CredentialEncryptionError(
            "PostgreSQL credential encryption is not configured."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise CredentialEncryptionError(
            "PostgreSQL credential encryption configuration is invalid."
        ) from None


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_password(encrypted_password: str) -> str:
    try:
        return _fernet().decrypt(encrypted_password.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError):
        raise CredentialEncryptionError(
            "Stored PostgreSQL credentials could not be decrypted."
        ) from None


def create_postgres_engine(
    *,
    username: str,
    password: str,
    host: str,
    port: int,
    database_name: str,
    sslmode: str,
) -> Engine:
    settings = get_settings()
    validated_address = resolve_public_postgres_address(host, port)
    url = URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database_name,
    )
    try:
        engine = create_engine(
            url,
            connect_args={
                "connect_timeout": settings.database_connection_timeout_seconds,
                "sslmode": sslmode,
                "hostaddr": validated_address,
            },
            pool_size=1,
            max_overflow=0,
            pool_timeout=settings.database_connection_timeout_seconds,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        def revalidate_destination(
            _dialect: object,
            _record: object,
            _args: tuple[object, ...],
            connect_args: dict[str, object],
        ) -> None:
            del _dialect, _record, _args
            connect_args["hostaddr"] = resolve_public_postgres_address(host, port)

        event.listen(engine, "do_connect", revalidate_destination)
        return engine
    except (SQLAlchemyError, ValueError):
        raise TargetConnectionError(
            "The database connection could not be established."
        ) from None


def verify_postgres_engine(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, ValueError):
        raise TargetConnectionError(
            "The database connection could not be established."
        ) from None
