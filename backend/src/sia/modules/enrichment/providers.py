"""Where enrichment gets web pages and AI answers from.

Real providers read the live web (WebFetcher) and call Claude. Fake providers serve canned,
self-consistent data so tests and the end-to-end suite run offline, for free, deterministically.
Settings refuse fake providers in production.
"""

import re
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from sia.ai.client import AnthropicLLMClient, FakeLLMClient, LLMClient
from sia.core.config import Settings
from sia.core.errors import AppError
from sia.modules.companies.domains import InvalidDomainError, normalize_domain
from sia.modules.enrichment.extraction import (
    Evidence,
    ExtractedProfile,
    IndustryFact,
    TextFact,
)
from sia.modules.enrichment.fetcher import PageText, WebFetcher


class EnrichmentUnavailableError(AppError):
    status_code = 503
    code = "enrichment_unavailable"

    def __init__(self) -> None:
        super().__init__("AI enrichment is not configured on this server.")


class SiteReader(Protocol):
    async def read(self, website: str) -> list[PageText]: ...


class WebSiteReader:
    async def read(self, website: str) -> list[PageText]:
        async with WebFetcher() as fetcher:
            return await fetcher.fetch_site(website)


def _fake_text(domain: str) -> str:
    name = domain.split(".")[0].capitalize()
    return (
        f"{name} builds workflow automation software for finance teams at mid-sized banks. "
        f"Our platform reconciles payments and automates month-end reporting. "
        f"We work with banks and insurers across Europe. "
        f"{name} is headquartered in Berlin, Germany."
    )


class FakeSiteReader:
    """A pretend website per domain (offline)."""

    async def read(self, website: str) -> list[PageText]:
        try:
            domain = normalize_domain(website)
        except InvalidDomainError:
            domain = "example.com"
        url = f"https://{domain}/"
        return [
            PageText(url=url, title=domain, text=_fake_text(domain), fetched_at=datetime.now(UTC))
        ]


def fake_profile(_system: str, content: str, _output_type: type[Any]) -> BaseModel:
    """A profile whose quotes really occur in FakeSiteReader's text (so they verify)."""
    url_match = re.search(r'<page url="([^"]+)"', content)
    url = url_match.group(1) if url_match else "https://example.com/"
    domain = re.sub(r"^https://|/$", "", url)
    text = _fake_text(domain)

    def fact(value: str, quote: str) -> TextFact:
        assert quote in text  # noqa: S101 -- invariant of the fake itself
        return TextFact(value=value, evidence=[Evidence(source_url=url, quote=quote)])

    return ExtractedProfile(
        description=fact(
            "Workflow automation software for finance teams at mid-sized banks.",
            "builds workflow automation software for finance teams at mid-sized banks",
        ),
        industry=IndustryFact(
            value="Fintech",
            evidence=[Evidence(source_url=url, quote="reconciles payments and automates")],
        ),
        products=[fact("Payment reconciliation", "Our platform reconciles payments")],
        target_customers=[fact("Banks and insurers", "We work with banks and insurers")],
        business_model=None,
        headquarters_city=fact("Berlin", "headquartered in Berlin, Germany"),
        headquarters_country=fact("Germany", "headquartered in Berlin, Germany"),
        employee_range=None,
        founded_year=None,
    )


def make_site_reader(settings: Settings) -> SiteReader:
    return FakeSiteReader() if settings.fetch_provider == "fake" else WebSiteReader()


def llm_configured(settings: Settings) -> bool:
    return settings.llm_provider == "fake" or settings.anthropic_api_key is not None


def make_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLMClient(fake_profile, model="fake-model")
    if settings.anthropic_api_key is None:
        raise EnrichmentUnavailableError()
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(), model=settings.enrichment_model
    )
