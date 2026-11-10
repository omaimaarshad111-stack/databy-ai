from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import verify_password
from app.core.rate_limit import auth_rate_limiter
from app.db.models import User

REGISTER_PAYLOAD = {
    "username": "test.user",
    "email": "test@example.com",
    "password": "Strong-password-123",
}


def register(api_client, **overrides):
    return api_client(
        "POST",
        "/api/v1/auth/register",
        json={**REGISTER_PAYLOAD, **overrides},
    )


def test_registration_hashes_password_and_returns_public_user(
    api_client, test_session_factory
) -> None:
    response = register(api_client)

    assert response.status_code == 201
    assert response.json()["email"] == REGISTER_PAYLOAD["email"]
    assert "hashed_password" not in response.json()
    with test_session_factory() as session:
        user = session.scalar(select(User).where(User.email == REGISTER_PAYLOAD["email"]))
        assert user is not None
        assert user.hashed_password != REGISTER_PAYLOAD["password"]
        assert verify_password(REGISTER_PAYLOAD["password"], user.hashed_password)


def test_duplicate_email_is_rejected(api_client) -> None:
    assert register(api_client).status_code == 201

    response = register(api_client, username="another.user")

    assert response.status_code == 409


def test_duplicate_username_is_rejected_case_insensitively(api_client) -> None:
    assert register(api_client).status_code == 201

    response = register(api_client, email="other@example.com", username="TEST.USER")

    assert response.status_code == 409


def test_registration_validates_email_and_password(api_client) -> None:
    bad_email = register(api_client, email="not-an-email")
    short_password = register(api_client, email="other@example.com", password="short")

    assert bad_email.status_code == 422
    assert short_password.status_code == 422
    assert '"short"' not in short_password.text
    assert all("input" not in error for error in short_password.json()["detail"])


def test_login_returns_access_token_and_rejects_wrong_password(api_client) -> None:
    assert register(api_client).status_code == 201

    login_response = api_client(
        "POST",
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    wrong_password_response = api_client(
        "POST",
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "incorrect-password"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["token_type"] == "bearer"
    assert wrong_password_response.status_code == 401


def test_current_user_requires_valid_access_token(api_client) -> None:
    registration = register(api_client)
    user_id = UUID(registration.json()["id"])
    login_response = api_client(
        "POST",
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    token = login_response.json()["access_token"]

    without_token = api_client("GET", "/api/v1/auth/me")
    with_token = api_client(
        "GET",
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert without_token.status_code == 401
    assert with_token.status_code == 200
    assert with_token.json()["id"] == str(user_id)
    assert "hashed_password" not in with_token.json()


def test_expired_and_invalid_tokens_are_rejected(api_client) -> None:
    register(api_client)
    expired_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        get_settings().jwt_secret_key,
        algorithm="HS256",
    )

    for token in (expired_token, "not-a-jwt"):
        response = api_client(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


def test_login_is_rate_limited(api_client, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_login_rate_limit", 2)
    auth_rate_limiter.clear()

    responses = [
        api_client(
            "POST",
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "not-a-valid-password"},
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert int(responses[-1].headers["Retry-After"]) > 0


def test_responses_include_request_correlation_id(api_client) -> None:
    response = api_client("GET", "/api/v1/health")

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32


def test_saved_query_patch_is_allowed_by_cors(api_client) -> None:
    response = api_client(
        "OPTIONS",
        "/api/v1/saved-queries/example",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
