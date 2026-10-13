"""HANA-only destination policy, staged in report mode before enforcement.

Resolve once and give the driver an IP, preserving the configured TLS identity.
No HTTP client or redirects are involved in this SQL/TCP connector.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


class HanaConnectorError(RuntimeError):
    """A closed error code; never retain driver messages or credentials."""

    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _csv(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def canonical_host(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not value or len(value) > 253:
        raise HanaConnectorError("HANA_HOST_INVALID")
    labels = value.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels):
        raise HanaConnectorError("HANA_HOST_INVALID")
    return value


def assert_tls_policy(host: str, *, encrypt: bool, verify: bool) -> None:
    if encrypt and verify:
        return
    approved = {
        canonical_host(value)
        for value in _csv(getattr(settings, "hana_insecure_tls_allowed_hosts", ""))
    }
    if getattr(settings, "hana_allow_insecure_tls", False) is not True or host not in approved:
        raise HanaConnectorError("HANA_TLS_REQUIRED", 403)


@dataclass(frozen=True)
class HanaDestination:
    host: str
    address: str


def resolve_destination(host: str, port: int) -> HanaDestination:
    """Check every resolved address, then pin the single address used by hdbcli.

    Private destinations require an explicit IP/CIDR approval; a DNS name alone
    cannot authorize a private address introduced by a rebinding response.
    """
    host = canonical_host(host)
    mode = getattr(settings, "hana_network_policy_mode", "report")
    if mode not in {"report", "enforce"}:
        raise HanaConnectorError("HANA_NETWORK_POLICY_INVALID", 503)
    try:
        allowed_hosts = {
            canonical_host(value) for value in _csv(getattr(settings, "hana_allowed_hosts", ""))
        }
        allowed_networks = [
            ipaddress.ip_network(value, strict=True)
            for value in _csv(getattr(settings, "hana_allowed_cidrs", ""))
        ]
    except (ValueError, HanaConnectorError):
        raise HanaConnectorError("HANA_NETWORK_POLICY_INVALID", 503) from None
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(ipaddress.ip_address(row[4][0]) for row in records))
    except (OSError, ValueError):
        raise HanaConnectorError("HANA_DNS_FAILED", 502) from None
    if not addresses:
        raise HanaConnectorError("HANA_DNS_FAILED", 502)
    for address in addresses:
        # IPv4-mapped IPv6 must obey the same policy as the embedded address.
        effective = getattr(address, "ipv4_mapped", None) or address
        explicitly_allowed = str(effective) in allowed_hosts or any(
            effective in network for network in allowed_networks
        )
        forbidden = (
            effective.is_loopback
            or effective.is_link_local
            or effective.is_unspecified
            or effective.is_multicast
            or effective.is_reserved
        )
        approved = not forbidden and (
            explicitly_allowed or (effective.is_global and host in allowed_hosts)
        )
        if not approved:
            # Fixed classifications only: do not log a user-supplied hostname.
            reason = (
                "special_address"
                if forbidden
                else "private_address"
                if not effective.is_global
                else "host_not_allowed"
            )
            logger.warning("HANA_NETWORK_POLICY mode=%s reason=%s", mode, reason)
            if mode == "enforce":
                raise HanaConnectorError("HANA_DESTINATION_DENIED", 403)
    return HanaDestination(host=host, address=str(addresses[0]))
