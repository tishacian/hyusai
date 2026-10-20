"""Shared destination checks for connector TCP/HTTP transports.

Report mode observes forbidden destinations without authorizing exceptions. DNS
is still resolved once and the transport connects to that exact address. HANA
retains its stricter existing host allow-list through the compatibility adapter.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


class ConnectorNetworkError(RuntimeError):
    def __init__(self, code: str, status_code: int = 400):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def csv(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def canonical_host(host: str) -> str:
    if not isinstance(host, str):
        raise ConnectorNetworkError("CONNECTOR_HOST_INVALID")
    value = host.strip().lower().rstrip(".")
    # Zone identifiers and libpq's multiple-host/socket syntaxes are not hosts.
    if "%" in value:
        raise ConnectorNetworkError("CONNECTOR_HOST_INVALID")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if (
        not value
        or len(value) > 253
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in value.split(".")
        )
    ):
        raise ConnectorNetworkError("CONNECTOR_HOST_INVALID")
    return value


@dataclass(frozen=True)
class Destination:
    host: str
    address: str
    port: int


def resolve_destination(
    host: str,
    port: int,
    *,
    mode: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
    allowed_cidrs: tuple[str, ...] = (),
    hana: bool = False,
) -> Destination:
    host = canonical_host(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ConnectorNetworkError("CONNECTOR_PORT_INVALID")
    mode = mode or settings.connector_network_policy_mode
    if mode not in {"report", "enforce"}:
        raise ConnectorNetworkError("CONNECTOR_NETWORK_POLICY_INVALID", 503)
    try:
        hosts = {canonical_host(value) for value in allowed_hosts or ()}
        networks = [ipaddress.ip_network(value, strict=True) for value in allowed_cidrs]
    except (ValueError, ConnectorNetworkError):
        raise ConnectorNetworkError("CONNECTOR_NETWORK_POLICY_INVALID", 503) from None
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(ipaddress.ip_address(row[4][0]) for row in records))
    except (OSError, ValueError):
        raise ConnectorNetworkError("CONNECTOR_DNS_FAILED", 502) from None
    if not addresses:
        raise ConnectorNetworkError("CONNECTOR_DNS_FAILED", 502)
    for address in addresses:
        effective = getattr(address, "ipv4_mapped", None) or address
        forbidden = (
            effective.is_loopback
            or effective.is_link_local
            or effective.is_unspecified
            or effective.is_multicast
            or effective.is_reserved
        )
        explicitly_allowed = str(effective) in hosts or any(
            effective in network for network in networks
        )
        approved = not forbidden and (
            explicitly_allowed or (effective.is_global and (allowed_hosts is None or host in hosts))
        )
        if not approved:
            reason = (
                "special_address"
                if forbidden
                else ("private_address" if not effective.is_global else "host_not_allowed")
            )
            logger.warning(
                "%s_NETWORK_POLICY mode=%s reason=%s", "HANA" if hana else "CONNECTOR", mode, reason
            )
            if mode == "enforce":
                raise ConnectorNetworkError("CONNECTOR_DESTINATION_DENIED", 403)
    return Destination(host, str(addresses[0]), port)


def postgresql_connection_options(host: str, port: int) -> dict[str, object]:
    destination = resolve_destination(host, port)
    return {
        "host": destination.host,
        "hostaddr": destination.address,
        "port": destination.port,
        "sslmode": "verify-full",
    }
