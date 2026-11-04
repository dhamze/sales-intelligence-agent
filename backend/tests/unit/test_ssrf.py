"""SSRF protection: connections may only go to public internet addresses (ADR-0009)."""

import httpcore2
import pytest

from sia.modules.enrichment.fetcher import FetchError, FetchFailure, WebFetcher
from sia.modules.enrichment.network import (
    BlockedAddressError,
    PublicOnlyBackend,
    is_public_address,
    public_only_transport,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata service (link-local)
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 -- "this host"
        "255.255.255.255",  # broadcast
        "224.0.0.1",  # multicast
        "192.0.2.10",  # documentation range
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique local (private)
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "2002:7f00:1::",  # 6to4 wrapping 127.0.0.1
        "ff02::1",  # IPv6 multicast
        "not-an-ip",
    ],
)
def test_internal_and_special_addresses_are_blocked(address: str) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.215.14", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_address(address)


def resolver_returning(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Records every TCP connection actually attempted (none should be, in these tests)."""
    attempted: list[tuple[str, int]] = []

    async def fake_connect(self: object, host: str, port: int, **_: object) -> None:
        attempted.append((host, port))
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(httpcore2.AnyIOBackend, "connect_tcp", fake_connect)
    return attempted


@pytest.mark.parametrize(
    ("resolved", "host", "port"),
    [
        (("127.0.0.1",), "innocent.example.com", 443),  # DNS points a public name at us
        (("93.184.215.14", "10.0.0.1"), "mixed.example.com", 443),  # one bad record is enough
        ((), "169.254.169.254", 80),  # IP literal of the metadata service
        (("93.184.215.14",), "example.com", 8080),  # non-web port
    ],
)
async def test_backend_refuses_before_any_connection_is_made(
    connections: list[tuple[str, int]], resolved: tuple[str, ...], host: str, port: int
) -> None:
    backend = PublicOnlyBackend(resolver_returning(*resolved))

    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp(host, port)

    assert connections == []


async def test_backend_connects_to_the_vetted_ip_not_the_name(
    connections: list[tuple[str, int]],
) -> None:
    """Defeats DNS rebinding: the socket goes to the address we checked, not a re-resolution."""
    backend = PublicOnlyBackend(resolver_returning("93.184.215.14"))

    with pytest.raises(AssertionError):
        await backend.connect_tcp("example.com", 443)

    assert connections == [("93.184.215.14", 443)]


async def test_the_real_http_client_uses_the_protected_backend(
    connections: list[tuple[str, int]],
) -> None:
    """End to end through httpx2: proves the backend is really wired into the transport."""
    transport = public_only_transport(resolver_returning("127.0.0.1"))

    async with WebFetcher(transport=transport) as fetcher:
        with pytest.raises(FetchError) as caught:
            await fetcher.fetch_page("https://rebinding.example.com/")

    assert caught.value.reason == FetchFailure.BLOCKED_ADDRESS
    assert connections == []
