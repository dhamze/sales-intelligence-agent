"""Fetching public company web pages, safely and politely (ADR-0009).

Safety: see network.py for connection-level SSRF protection. On top of that, every URL (including
each redirect hop) must be http/https on port 80/443 with a public domain name; responses are
capped in size and time; only HTML is accepted.

Politeness: robots.txt is honoured (RFC 9309), at most one request per second per site, and the
bot identifies itself with a User-Agent that links to the project.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx2
import structlog
import trafilatura

from sia.modules.companies.domains import InvalidDomainError, normalize_domain, normalize_url
from sia.modules.enrichment.network import ALLOWED_PORTS, BlockedAddressError, public_only_transport

logger = structlog.get_logger(__name__)

BOT_NAME = "SalesIntelligenceBot"
USER_AGENT = f"{BOT_NAME}/0.1 (+https://github.com/dhamze/sales-intelligence-agent)"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 5
MAX_TEXT_CHARS = 15_000  # per page, after extraction
PAGE_TIMEOUT_SECONDS = 20.0
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
HTML_TYPES = ("text/html", "application/xhtml+xml")

# Pages most likely to say what a company does, in order of preference.
INTERESTING_PATHS = (
    ("about", "about-us", "company", "who-we-are", "our-story"),
    ("products", "product", "solutions", "platform", "services", "features"),
    ("customers", "case-studies", "clients", "industries"),
)


class FetchFailure(StrEnum):
    INVALID_URL = "invalid_url"
    BLOCKED_ADDRESS = "blocked_address"
    ROBOTS_DISALLOWED = "robots_disallowed"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    TOO_LARGE = "too_large"
    NOT_HTML = "not_html"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    NO_TEXT = "no_text"


class FetchError(Exception):
    def __init__(self, reason: FetchFailure, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Page:
    url: str  # final URL after redirects
    html: str
    fetched_at: datetime


@dataclass(frozen=True)
class PageText:
    url: str
    title: str | None
    text: str
    fetched_at: datetime


def checked_url(url: str) -> str:
    """Normalise and validate a URL we are about to request."""
    try:
        clean = normalize_url(url)
    except InvalidDomainError as exc:
        raise FetchError(FetchFailure.INVALID_URL, str(exc)) from exc
    parts = urlsplit(clean)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchError(FetchFailure.INVALID_URL, f"port {port} is not allowed")
    return clean


class _Robots:
    """robots.txt rules for one site (RFC 9309 semantics for errors)."""

    def __init__(self, parser: robotparser.RobotFileParser | None, allow_all: bool) -> None:
        self._parser = parser
        self._allow_all = allow_all

    def allows(self, url: str) -> bool:
        if self._parser is None:
            return self._allow_all
        return self._parser.can_fetch(BOT_NAME, url)


@dataclass
class _Site:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float = 0.0
    robots: _Robots | None = None


class WebFetcher:
    """Fetches pages for enrichment. One instance per job; not shared across tenants."""

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._client = httpx2.AsyncClient(
            transport=transport or public_only_transport(),
            follow_redirects=False,  # we follow them ourselves, re-checking every hop
            timeout=httpx2.Timeout(10.0, connect=5.0),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            trust_env=False,  # never use proxies from the environment (they'd bypass checks)
        )
        self._sites: dict[str, _Site] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WebFetcher":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # --- low level ---------------------------------------------------------------------------

    def _site(self, url: str) -> _Site:
        host = urlsplit(url).hostname or ""
        return self._sites.setdefault(host, _Site())

    async def _polite_get(self, url: str, max_bytes: int) -> tuple[httpx2.Response, bytes]:
        site = self._site(url)
        async with site.lock:
            wait = site.last_request + MIN_SECONDS_BETWEEN_REQUESTS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with self._client.stream("GET", url) as response:
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError(FetchFailure.TOO_LARGE, f"{declared} bytes")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise FetchError(FetchFailure.TOO_LARGE, f"over {max_bytes} bytes")
                    return response, bytes(body)
            except BlockedAddressError as exc:
                raise FetchError(FetchFailure.BLOCKED_ADDRESS, str(exc)) from exc
            except httpx2.TimeoutException as exc:
                raise FetchError(FetchFailure.TIMEOUT, url) from exc
            except httpx2.TransportError as exc:
                cause = exc.__cause__ or exc.__context__
                if isinstance(cause, BlockedAddressError):
                    raise FetchError(FetchFailure.BLOCKED_ADDRESS, str(cause)) from exc
                raise FetchError(FetchFailure.NETWORK_ERROR, type(exc).__name__) from exc
            finally:
                site.last_request = time.monotonic()

    async def _robots_for(self, url: str) -> _Robots:
        site = self._site(url)
        if site.robots is None:
            parts = urlsplit(url)
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            site.robots = await self._load_robots(robots_url)
        return site.robots

    async def _load_robots(self, robots_url: str) -> _Robots:
        try:
            url = robots_url
            for _ in range(MAX_REDIRECTS + 1):
                response, body = await self._polite_get(url, MAX_ROBOTS_BYTES)
                if response.is_redirect and "location" in response.headers:
                    url = checked_url(urljoin(url, response.headers["location"]))
                    continue
                break
        except FetchError as exc:
            if exc.reason == FetchFailure.BLOCKED_ADDRESS:
                raise
            # RFC 9309: robots.txt unreachable -> assume complete disallow.
            return _Robots(None, allow_all=False)
        if 400 <= response.status_code < 500:
            return _Robots(None, allow_all=True)  # RFC 9309: "unavailable" -> no restrictions
        if response.status_code >= 500 or response.is_redirect:
            return _Robots(None, allow_all=False)
        parser = robotparser.RobotFileParser()
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        return _Robots(parser, allow_all=True)

    # --- pages -------------------------------------------------------------------------------

    async def fetch_page(self, url: str) -> Page:
        url = checked_url(url)
        async with asyncio.timeout(PAGE_TIMEOUT_SECONDS):
            try:
                for _ in range(MAX_REDIRECTS + 1):
                    if not (await self._robots_for(url)).allows(url):
                        raise FetchError(FetchFailure.ROBOTS_DISALLOWED, url)
                    response, body = await self._polite_get(url, MAX_PAGE_BYTES)
                    if response.is_redirect and "location" in response.headers:
                        url = checked_url(urljoin(url, response.headers["location"]))
                        continue
                    if response.status_code != 200:
                        raise FetchError(FetchFailure.HTTP_ERROR, f"status {response.status_code}")
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(HTML_TYPES):
                        raise FetchError(FetchFailure.NOT_HTML, content_type or "unknown")
                    html = body.decode(response.charset_encoding or "utf-8", errors="replace")
                    return Page(url=url, html=html, fetched_at=datetime.now(UTC))
            except TimeoutError as exc:
                raise FetchError(FetchFailure.TIMEOUT, url) from exc
        raise FetchError(FetchFailure.TOO_MANY_REDIRECTS, url)

    async def fetch_site(self, website: str, max_extra_pages: int = 3) -> list[PageText]:
        """Homepage plus up to `max_extra_pages` informative pages on the same site."""
        home = await self.fetch_page(website)
        pages = [home]
        for link in pick_interesting_links(home.html, home.url, max_extra_pages):
            try:
                pages.append(await self.fetch_page(link))
            except FetchError as exc:
                logger.info("enrichment_page_skipped", reason=exc.reason.value)
        texts = [t for t in (page_text(p) for p in pages) if t is not None]
        if not texts:
            raise FetchError(FetchFailure.NO_TEXT, home.url)
        return texts


# --- HTML helpers ---------------------------------------------------------------------------


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def _same_site(url: str, base: str) -> bool:
    try:
        return normalize_domain(url) == normalize_domain(base)
    except InvalidDomainError:
        return False


def pick_interesting_links(html: str, base_url: str, limit: int) -> list[str]:
    """Same-site links whose path looks like an about / products / customers page."""
    parser = _LinkParser()
    parser.feed(html)
    candidates: dict[str, str] = {}  # path -> absolute URL (dedupe)
    for href in parser.links:
        absolute = urljoin(base_url, href.strip())
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or not _same_site(absolute, base_url):
            continue
        path = parts.path.rstrip("/").lower()
        if path and path not in candidates:
            candidates[path] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    chosen: list[str] = []
    for keywords in INTERESTING_PATHS:
        for path, url in candidates.items():
            last_segment = path.rsplit("/", 1)[-1]
            if last_segment in keywords and url not in chosen and path.count("/") <= 2:
                chosen.append(url)
                break
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def page_text(page: Page) -> PageText | None:
    """Main readable text of a page (navigation, cookie banners and boilerplate removed)."""
    text = trafilatura.extract(
        page.html,
        url=page.url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text.strip()) < 40:
        return None
    metadata = trafilatura.extract_metadata(page.html)
    title = metadata.title if metadata is not None else None
    return PageText(
        url=page.url, title=title, text=text[:MAX_TEXT_CHARS], fetched_at=page.fetched_at
    )
