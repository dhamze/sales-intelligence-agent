"""Normalising company domains and website URLs.

The normalised domain is the de-duplication key for companies, so every input form of the
same company must produce the same value:

    https://WWW.Blog.Acme.co.uk:443/about?x=1  ->  acme.co.uk
    münchen.de                                  ->  xn--mnchen-3ya.de   (ASCII "punycode" form)
    foo.github.io                               ->  foo.github.io       (hosted site, not github.io)

"Registrable domain" is decided by the Public Suffix List (which knows `co.uk` is a suffix).
We use the list bundled with `tldextract` and never download it at runtime.
"""

import re
from urllib.parse import urlsplit, urlunsplit

import tldextract

_extract = tldextract.TLDExtract(
    suffix_list_urls=(),  # offline: bundled snapshot only
    cache_dir=None,
    # Treat hosting platforms (github.io, herokuapp.com, ...) as suffixes, so
    # different sites on them are different companies.
    include_psl_private_domains=True,
)

_ASCII_HOST = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
MAX_URL_LENGTH = 2048


class InvalidDomainError(ValueError):
    pass


def _host_of(value: str) -> tuple[str, str]:
    """Return (scheme, lowercased host) of a URL or bare domain."""
    raw = value.strip()
    if not raw or len(raw) > MAX_URL_LENGTH or any(c.isspace() for c in raw):
        raise InvalidDomainError("Not a valid domain or URL.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = parts.hostname  # strips user info and port, lowercases
    except ValueError as exc:
        raise InvalidDomainError("Not a valid domain or URL.") from exc
    if not host:
        raise InvalidDomainError("Not a valid domain or URL.")
    return parts.scheme.lower(), host.rstrip(".")


def _to_ascii(host: str) -> str:
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidDomainError("Not a valid domain name.") from exc
    if len(ascii_host) > 253 or not _ASCII_HOST.match(ascii_host):
        raise InvalidDomainError("Not a valid domain name.")
    return ascii_host


def normalize_domain(value: str) -> str:
    """Registrable domain in ASCII form. Raises InvalidDomainError (e.g. IPs, localhost)."""
    _, host = _host_of(value)
    ascii_host = _to_ascii(host)
    parts = _extract(ascii_host)
    if not parts.domain or not parts.suffix:
        raise InvalidDomainError("Not a public domain name.")
    return f"{parts.domain}.{parts.suffix}"


def normalize_url(value: str) -> str:
    """A clean absolute http(s) URL with a public host (fragment removed)."""
    scheme, host = _host_of(value)
    if scheme not in ("http", "https"):
        raise InvalidDomainError("Only http and https URLs are allowed.")
    normalize_domain(host)  # host must be a public domain
    raw = value.strip() if "://" in value else "https://" + value.strip()
    parts = urlsplit(raw)
    netloc = _to_ascii(host) + (f":{parts.port}" if parts.port else "")
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
