# ADR-0009: SSRF-safe fetching of user-supplied websites

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Enrichment fetches company websites whose URLs come from users (forms and CSV imports). A
server that fetches attacker-chosen URLs is the classic setup for **server-side request forgery
(SSRF)**: a "website" pointing at `169.254.169.254` (cloud credentials), `10.x` / `localhost`
(internal services) or an internal hostname turns our server into a proxy into the private
network. Checking only the URL text is not enough: with **DNS rebinding**, a name resolves to a
public address when checked and to an internal one when the HTTP library connects.

## Decision

Defence in layers, in `sia/modules/enrichment/network.py` and `fetcher.py`:

1. **URL rules** (every request, including every redirect hop): `http`/`https` only, ports 80
   and 443 only, a public registrable domain (no IP literals, `localhost` or unknown TLDs).
   Redirects are followed manually (at most 5) so each hop is re-checked.
2. **Connection rules:** a custom `httpcore2` network backend resolves the hostname itself,
   refuses if **any** resolved address is not globally routable unicast (private, loopback,
   link-local, carrier-grade NAT, reserved, multicast, and IPv4 hidden in IPv6 forms), then
   opens the socket to the **vetted IP**. TLS still verifies the certificate for the original
   hostname.
3. **No environment proxies** (`trust_env=False`): a proxy would connect on our behalf.
4. **Resource limits:** 2 MB per response (declared and streamed), 20 s per page, HTML only.
5. **Politeness:** robots.txt per RFC 9309 (unreachable or 5xx means disallow, 4xx means allow),
   one request per second per site, an honest User-Agent linking to the project.

`httpx2` has no public option for the network backend, so the transport's pool is configured
through a private attribute. Both libraries are pinned, and a test drives the real client end
to end and fails if the backend is not in effect (verified by deliberately removing it).

## Consequences

- Sites hosted on private addresses can't be enriched (intended).
- Some sites block bots via robots.txt; they are reported as "robots disallowed", not retried.
- A library upgrade that changes `httpx2` internals fails the test suite rather than silently
  removing protection.
