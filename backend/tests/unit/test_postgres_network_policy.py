import socket
from typing import Any

import pytest
from sqlalchemy import create_engine as create_test_engine

from app.core.config import get_settings
from app.database_targets.exceptions import TargetConnectionError
from app.database_targets.network_policy import resolve_public_postgres_address
from app.database_targets.postgres_target import create_postgres_engine


def address_record(value: str) -> tuple:
    family = socket.AF_INET6 if ":" in value else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (value, 5432))


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.4",
        "172.20.1.2",
        "192.168.10.5",
        "169.254.1.2",
        "169.254.169.254",
        "100.100.100.200",
        "168.63.129.16",
        "0.0.0.0",
        "240.0.0.1",
        "fc00::1",
        "fe80::1",
        "::ffff:192.168.1.1",
    ],
)
def test_prohibited_ip_literals_are_rejected(host: str) -> None:
    with pytest.raises(TargetConnectionError):
        resolve_public_postgres_address(host, 5432)


def test_localhost_hostname_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            address_record("127.0.0.1"),
            address_record("::1"),
        ],
    )
    with pytest.raises(TargetConnectionError):
        resolve_public_postgres_address("localhost", 5432)


def test_public_postgres_hostname_is_resolved_and_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    def fake_getaddrinfo(hostname: str, port: int, *, type: int) -> list[tuple]:
        observed.update(hostname=hostname, port=port, socket_type=type)
        return [address_record("1.1.1.1"), address_record("8.8.8.8")]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(get_settings(), "postgres_allowed_hosts", ["db.example.com"])

    assert resolve_public_postgres_address("db.example.com.", 5432) == "1.1.1.1"
    assert observed == {
        "hostname": "db.example.com",
        "port": 5432,
        "socket_type": socket.SOCK_STREAM,
    }


def test_postgres_host_allowlist_rejects_unapproved_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "postgres_allowed_hosts", ["approved.example.com"])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Disallowed hosts must be rejected before DNS resolution")
        ),
    )
    with pytest.raises(TargetConnectionError, match="not in the configured allowlist"):
        resolve_public_postgres_address("other.example.com", 5432)


@pytest.mark.parametrize(
    "answers",
    [
        ["8.8.8.8", "10.0.0.5"],
        ["8.8.8.8", "169.254.169.254"],
        ["8.8.8.8", "fd00::1"],
    ],
)
def test_hostname_with_any_prohibited_dns_answer_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    answers: list[str],
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [address_record(answer) for answer in answers],
    )

    with pytest.raises(TargetConnectionError):
        resolve_public_postgres_address("db.example.com", 5432)


def test_dns_resolution_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(*_args, **_kwargs):
        raise socket.gaierror("resolver detail")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    with pytest.raises(TargetConnectionError, match="could not be resolved safely"):
        resolve_public_postgres_address("db.example.com", 5432)


def test_empty_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(TargetConnectionError, match="did not resolve"):
        resolve_public_postgres_address("db.example.com", 5432)


def test_ip_literal_is_pinned_without_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_resolution(*_args, **_kwargs):
        raise AssertionError("IP literals must not trigger DNS")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    assert resolve_public_postgres_address("1.1.1.1", 5432) == "1.1.1.1"


def test_postgres_engine_uses_resolved_ip_without_losing_tls_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.database_targets.postgres_target as postgres_target

    captured: dict[str, Any] = {}
    engine_sentinel = create_test_engine("sqlite://")
    resolved_addresses = iter(["1.1.1.1", "8.8.8.8"])
    resolutions = []

    def resolve(host: str, port: int) -> str:
        resolutions.append((host, port))
        return next(resolved_addresses)

    listener = {}
    monkeypatch.setattr(postgres_target, "resolve_public_postgres_address", resolve)
    monkeypatch.setattr(
        postgres_target,
        "create_engine",
        lambda url, **kwargs: (
            captured.update(url=url, **kwargs) or engine_sentinel
        ),
    )
    monkeypatch.setattr(
        postgres_target.event,
        "listen",
        lambda _engine, _event_name, callback: listener.update(callback=callback),
    )
    engine = create_postgres_engine(
        username="reader",
        password="test-password",
        host="db.example.com",
        port=5432,
        database_name="analytics",
        sslmode="verify-full",
    )
    assert engine is engine_sentinel
    assert captured["connect_args"]["hostaddr"] == "1.1.1.1"
    assert captured["url"].host == "db.example.com"
    assert captured["connect_args"]["sslmode"] == "verify-full"
    connect_args = {"hostaddr": "1.1.1.1"}
    listener["callback"](None, None, (), connect_args)
    assert connect_args["hostaddr"] == "8.8.8.8"
    assert resolutions == [("db.example.com", 5432), ("db.example.com", 5432)]
    engine.dispose()


def test_ipv4_mapped_ipv6_is_rejected_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TargetConnectionError):
        resolve_public_postgres_address("::ffff:192.168.1.1", 5432)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [address_record("::ffff:1.1.1.1")],
    )
    assert resolve_public_postgres_address("db.example.com", 5432) == "1.1.1.1"
