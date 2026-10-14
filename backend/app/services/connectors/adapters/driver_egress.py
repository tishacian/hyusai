"""Scoped Python-driver egress inside a single isolated runner process.

Keep original hostnames for TLS while pinning every allowed TCP destination.
Discovered replicas outside the administrator-declared seeds fail closed.
This is not used in the API, in shared threads, or for native C driver sockets.
"""

import socket
from contextlib import contextmanager

from app.services.connectors.network_policy import (
    ConnectorNetworkError,
    canonical_host,
    resolve_destination,
)


@contextmanager
def pinned_python_driver(hosts):
    destinations = [resolve_destination(host, port) for host, port in hosts]
    names = {(d.host, d.port): d for d in destinations}
    addresses = {(d.address, d.port): d for d in destinations}
    original_dns, original_socket = socket.getaddrinfo, socket.socket

    def resolve(host, port, *args, **kwargs):
        host = canonical_host(host)
        destination = names.get((host, port)) or addresses.get((host, port))
        if destination is None:
            raise ConnectorNetworkError("CONNECTOR_DISCOVERED_HOST_DENIED", 403)
        return original_dns(destination.address, port, *args, **kwargs)

    class PinnedSocket(original_socket):
        def _address(self, address):
            if self.family not in (socket.AF_INET, socket.AF_INET6):
                raise ConnectorNetworkError("CONNECTOR_DESTINATION_DENIED", 403)
            host, port = address[:2]
            destination = names.get((canonical_host(host), port)) or addresses.get(
                (canonical_host(host), port)
            )
            if destination is None:
                raise ConnectorNetworkError("CONNECTOR_DISCOVERED_HOST_DENIED", 403)
            return (destination.address, port, *address[2:])

        def connect(self, address):
            return super().connect(self._address(address))

        def connect_ex(self, address):
            return super().connect_ex(self._address(address))

    socket.getaddrinfo, socket.socket = resolve, PinnedSocket
    try:
        yield destinations
    finally:
        socket.getaddrinfo, socket.socket = original_dns, original_socket
