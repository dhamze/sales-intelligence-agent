"""Fetcher behaviour with a simulated web (httpx2.MockTransport): URL rules, redirects,
robots.txt, limits and page selection."""

import time
from collections.abc import Callable

import httpx2
import pytest

from sia.modules.enrichment import fetcher as fetcher_module
from sia.modules.enrichment.fetcher import (
    FetchError,
    FetchFailure,
    WebFetcher,
    pick_interesting_links,
)

Routes = dict[str, httpx2.Response | Callable[[], httpx2.Response]]

HOME = """<html><head><title>Initech</title></head><body>
<nav><a href="/about">About</a> <a href="/products/">Products</a>
<a href="/blog/2026/post">Blog</a>
<a href="https://twitter.com/initech">Twitter</a> <a href="mailto:hi@initech.com">Mail</a></nav>
<main><h1>Initech</h1><p>Initech builds TPS report automation software for banks and insurers
across Europe. Our platform helps finance teams close their books faster.</p></main>
</body></html>"""

ABOUT = """<html><body><main><h1>About Initech</h1><p>Founded in 1999 in Austin, Texas, Initech
employs around 250 people and serves more than 400 enterprise customers.</p></main></body></html>"""


def html(body: str) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def web(routes: Routes) -> httpx2.MockTransport:
    """A fake internet: URL -> response. robots.txt defaults to 'allow all'."""
    routes = {"https://initech.com/robots.txt": httpx2.Response(404), **routes}

    def handler(request: httpx2.Request) -> httpx2.Response:
        route = routes.get(str(request.url))
        if route is None:
            return httpx2.Response(404)
        return route() if callable(route) else route

    return httpx2.MockTransport(handler)


@pytest.fixture(autouse=True)
def no_politeness_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher_module, "MIN_SECONDS_BETWEEN_REQUESTS", 0.0)


async def fetch(routes: Routes, url: str = "https://initech.com/") -> fetcher_module.Page:
    async with WebFetcher(transport=web(routes)) as f:
        return await f.fetch_page(url)


async def failure(routes: Routes, url: str = "https://initech.com/") -> FetchFailure:
    with pytest.raises(FetchError) as caught:
        await fetch(routes, url)
    return caught.value.reason


async def test_fetches_site_with_its_most_informative_pages() -> None:
    routes: Routes = {
        "https://initech.com/": html(HOME),
        "https://initech.com/about": html(ABOUT),
        "https://initech.com/products/": html("<p>short</p>"),  # too little text: skipped
    }
    async with WebFetcher(transport=web(routes)) as f:
        pages = await f.fetch_site("initech.com")

    assert [p.url for p in pages] == ["https://initech.com/", "https://initech.com/about"]
    assert "TPS report automation" in pages[0].text
    assert "Founded in 1999" in pages[1].text
    assert "About" not in pages[0].text.split("\n")[0]  # navigation stripped


@pytest.mark.parametrize(
    "url",
    ["ftp://initech.com/", "https://initech.com:8443/", "http://127.0.0.1/", "http://localhost/"],
)
async def test_invalid_urls_are_rejected_before_any_request(url: str) -> None:
    assert await failure({}, url) == FetchFailure.INVALID_URL


@pytest.mark.parametrize(
    "location",
    ["http://169.254.169.254/latest/meta-data/", "http://localhost/admin", "file:///etc/passwd"],
)
async def test_redirects_to_internal_targets_are_rejected(location: str) -> None:
    routes: Routes = {"https://initech.com/": httpx2.Response(302, headers={"location": location})}

    assert await failure(routes) == FetchFailure.INVALID_URL


async def test_redirects_are_followed_with_a_limit() -> None:
    ok: Routes = {
        "https://initech.com/": httpx2.Response(301, headers={"location": "/home"}),
        "https://initech.com/home": html(HOME),
    }
    loop: Routes = {
        "https://initech.com/": httpx2.Response(302, headers={"location": "/"}),
    }

    assert (await fetch(ok)).url == "https://initech.com/home"
    assert await failure(loop) == FetchFailure.TOO_MANY_REDIRECTS


@pytest.mark.parametrize(
    ("robots", "expected"),
    [
        (httpx2.Response(200, text="User-agent: *\nDisallow: /"), FetchFailure.ROBOTS_DISALLOWED),
        (
            httpx2.Response(200, text="User-agent: SalesIntelligenceBot\nDisallow: /"),
            FetchFailure.ROBOTS_DISALLOWED,
        ),
        (httpx2.Response(503), FetchFailure.ROBOTS_DISALLOWED),  # RFC 9309: assume disallow
        (httpx2.Response(200, text="User-agent: OtherBot\nDisallow: /"), None),
        (httpx2.Response(404), None),  # RFC 9309: no robots.txt -> allowed
    ],
)
async def test_robots_txt_is_respected(
    robots: httpx2.Response, expected: FetchFailure | None
) -> None:
    routes: Routes = {"https://initech.com/robots.txt": robots, "https://initech.com/": html(HOME)}

    if expected is None:
        assert (await fetch(routes)).url == "https://initech.com/"
    else:
        assert await failure(routes) == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx2.Response(404), FetchFailure.HTTP_ERROR),
        (
            httpx2.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"),
            FetchFailure.NOT_HTML,
        ),
        (
            httpx2.Response(
                200, headers={"content-type": "text/html", "content-length": "999999999"}
            ),
            FetchFailure.TOO_LARGE,
        ),
        (
            httpx2.Response(200, headers={"content-type": "text/html"}, content=b"x" * 2_100_000),
            FetchFailure.TOO_LARGE,  # no Content-Length: counted while streaming
        ),
    ],
)
async def test_unusable_responses(response: httpx2.Response, expected: FetchFailure) -> None:
    assert await failure({"https://initech.com/": response}) == expected


async def test_pages_on_one_site_are_fetched_politely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher_module, "MIN_SECONDS_BETWEEN_REQUESTS", 0.2)
    routes: Routes = {"https://initech.com/": html(HOME)}

    started = time.monotonic()
    await fetch(routes)  # robots.txt, then the page: two requests to the same site
    elapsed = time.monotonic() - started

    assert elapsed >= 0.2


def test_link_selection_prefers_about_products_customers_on_the_same_site() -> None:
    page = """
      <a href="/careers">Careers</a> <a href="/about-us">About</a>
      <a href="https://evil.example/about">Elsewhere</a> <a href="/solutions">Solutions</a>
      <a href="/customers">Customers</a> <a href="/a/b/c/products">Deep</a>
      <a href="javascript:alert(1)">x</a> <a href="https://shop.initech.com/products">Shop</a>
    """

    links = pick_interesting_links(page, "https://initech.com/", limit=3)

    assert links == [
        "https://initech.com/about-us",
        "https://initech.com/solutions",
        "https://initech.com/customers",
    ]
