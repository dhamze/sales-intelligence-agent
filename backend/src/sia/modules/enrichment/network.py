"""Network safety for fetching user-supplied URLs (SSRF protection, ADR-0009).

The threat: a "company website" that points at an internal address, e.g. the cloud metadata
service at 169.254.169.254, a database on 10.0.0.5 or an admin panel on localhost, turning
our server into a proxy into the private network.

Defences, in layers:
1. URL rules (fetcher.py): http/https only, ports 80/443 only, a public domain name.
2. Connection rules (here): the HOSTNAME IS RESOLVED BY US and every resolved address must be
   public; the socket is then opened to that vetted IP. Checking the name and letting the HTTP
   library resolve it again would be open to DNS rebinding (the name resolves to a public IP
   for the check and to 127.0.0.1 for the connection).
3. No proxies from the environment: a proxy would make the connection on our behalf,
   bypassing rule 2.

TLS is unaffected: certificates are still verified against the original hostname.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpcore2
import httpx2

ALLOWED_PORTS = frozenset({80, 443})

Resolver = Callable[[str, int], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class BlockedAddressError(httpcore2.ConnectError):
    """The destination is not a public internet address (or not an allowed port)."""


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4 addresses smuggled inside IPv6 forms (::ffff:10.0.0.1, 6to4, Teredo)."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    return None


def is_public_address(address: str | IPAddress) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(address) if isinstance(address, str) else address
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return is_public_address(embedded)
    # is_global is False for private, loopback, link-local, carrier-grade NAT (100.64/10),
    # documentation, benchmarking and reserved ranges; multicast is excluded separately.
    return ip.is_global and not ip.is_multicast


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


class PublicOnlyBackend(httpcore2.AsyncNetworkBackend):
    """Opens TCP connections only to public addresses, after resolving names itself."""

    def __init__(self, resolver: Resolver = system_resolver) -> None:
        self._resolver = resolver
        self._backend = httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 -- signature set by httpcore2
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if port not in ALLOWED_PORTS:
            raise BlockedAddressError(f"Port {port} is not allowed.")
        try:
            addresses = [str(ipaddress.ip_address(host))]  # already an IP literal
        except ValueError:
            try:
                addresses = await self._resolver(host, port)
            except OSError as exc:
                raise httpcore2.ConnectError(f"Could not resolve {host}.") from exc
        if not addresses:
            raise httpcore2.ConnectError(f"Could not resolve {host}.")
        # Refuse if ANY address is internal: a name mixing public and private records is hostile.
        if not all(is_public_address(a) for a in addresses):
            raise BlockedAddressError(f"{host} resolves to a non-public address.")
        return await self._backend.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 -- signature set by httpcore2
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise BlockedAddressError("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def public_only_transport(resolver: Resolver = system_resolver) -> httpx2.AsyncHTTPTransport:
    """An HTTP transport whose every connection goes through PublicOnlyBackend."""
    transport = httpx2.AsyncHTTPTransport(trust_env=False, retries=0)
    pool = transport._pool
    if not isinstance(pool, httpcore2.AsyncConnectionPool):  # e.g. a proxy pool
        raise RuntimeError("Unexpected httpx2 transport internals; refusing to fetch.")
    pool._network_backend = PublicOnlyBackend(resolver)
    return transport
