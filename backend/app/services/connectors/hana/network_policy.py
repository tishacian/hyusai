"""HANA-only destination policy, staged in report mode before enforcement.

Resolve once and give the driver an IP, preserving the configured TLS identity.
No HTTP client or redirects are involved in this SQL/TCP connector.
"""

from __future__ import annotations

import socket as socket  # compatibility for callers/tests patching the resolver
from dataclasses import dataclass

from app.core.config import settings
from app.services.connectors import network_policy as common


class HanaConnectorError(RuntimeError):
    """A closed error code; never retain driver messages or credentials."""

    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _csv(value: object) -> tuple[str, ...]:
    return common.csv(value)


def canonical_host(host: str) -> str:
    try:
        return common.canonical_host(host)
    except common.ConnectorNetworkError as exc:
        raise HanaConnectorError(exc.code.replace("CONNECTOR_", "HANA_"), exc.status_code) from None


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
    """Keep S0's allow-list and codes; either enforced policy remains enforced."""
    legacy_mode = settings.hana_network_policy_mode
    common_mode = settings.connector_network_policy_mode
    if legacy_mode not in {"report", "enforce"} or common_mode not in {"report", "enforce"}:
        raise HanaConnectorError("HANA_NETWORK_POLICY_INVALID", 503)
    try:
        destination = common.resolve_destination(
            host,
            port,
            mode="enforce" if "enforce" in {legacy_mode, common_mode} else "report",
            allowed_hosts=_csv(settings.hana_allowed_hosts),
            allowed_cidrs=_csv(settings.hana_allowed_cidrs),
            hana=True,
        )
        return HanaDestination(destination.host, destination.address)
    except common.ConnectorNetworkError as exc:
        raise HanaConnectorError(exc.code.replace("CONNECTOR_", "HANA_"), exc.status_code) from None
