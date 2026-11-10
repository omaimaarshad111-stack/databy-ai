import ipaddress
import socket

from app.core.config import get_settings
from app.database_targets.exceptions import TargetConnectionError

_CLOUD_METADATA_ADDRESSES = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("169.254.169.254"),
}


def _normalize_host(
    host: str,
) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            hostname = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise TargetConnectionError(
                "The PostgreSQL host is not a valid hostname."
            ) from None
        labels = hostname.split(".")
        if (
            len(hostname) > 253
            or len(labels) < 2
            or hostname == "localhost"
            or hostname.endswith(".localhost")
            or any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                or any(
                    not (
                        character.isascii()
                        and (character.isalnum() or character == "-")
                    )
                    for character in label
                )
                for label in labels
            )
        ):
            raise TargetConnectionError(
                "The PostgreSQL host is not a valid public hostname."
            ) from None
        return hostname, None
    if address.version == 6 and address.scope_id is not None:
        raise TargetConnectionError(
            "Scoped IPv6 addresses are not allowed for PostgreSQL."
        )
    return str(address), address


def resolve_public_postgres_address(host: str, port: int) -> str:
    normalized_host, literal_address = _normalize_host(host)
    settings = get_settings()
    allowed_hosts = [
        _normalize_host(allowed_host)[0]
        for allowed_host in settings.postgres_allowed_hosts
    ]
    if settings.app_env.lower() == "production" and not allowed_hosts:
        raise TargetConnectionError(
            "The PostgreSQL destination allowlist is not configured."
        )
    if allowed_hosts and normalized_host not in allowed_hosts:
        raise TargetConnectionError(
            "The PostgreSQL destination is not in the configured allowlist."
        )

    if literal_address is None:
        hostname = normalized_host
        if not hostname:
            raise TargetConnectionError(
                "The PostgreSQL host is not an allowed public address."
            ) from None
        try:
            records = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError):
            raise TargetConnectionError(
                "The PostgreSQL host could not be resolved safely."
            ) from None

        addresses = []
        for record in records:
            try:
                resolved_host = record[4][0]
                if "%" in resolved_host:
                    raise ValueError
                address = ipaddress.ip_address(resolved_host)
            except (IndexError, ValueError):
                raise TargetConnectionError(
                    "The PostgreSQL host resolved to an invalid address."
                ) from None
            addresses.append(address)
    else:
        addresses = [literal_address]

    if not addresses:
        raise TargetConnectionError(
            "The PostgreSQL host did not resolve to an address."
        )

    for address in addresses:
        mapped_address = getattr(address, "ipv4_mapped", None)
        effective_address = mapped_address or address
        if (
            (address.version == 6 and address.scope_id is not None)
            or not effective_address.is_global
            or effective_address in _CLOUD_METADATA_ADDRESSES
        ):
            raise TargetConnectionError(
                "The PostgreSQL host resolves to a prohibited network address."
            )

    first_address = addresses[0]
    return str(getattr(first_address, "ipv4_mapped", None) or first_address)
