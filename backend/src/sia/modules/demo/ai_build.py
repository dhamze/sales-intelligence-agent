"""Generate the sample data's AI content ONCE, with the same pipeline as the live product.

For every sample company: extract a profile from its (fictional) website text, verify the
evidence, apply the "fill only empty fields" rule, score it against the sample ICP, build the
brief's sources exactly as the app does, write the brief and verify its citations. The result
is saved as `sample_ai.json` and copied into workspaces that load sample data, so the public
demo shows real AI output without making AI calls (decision 2026-11-04: $0 ongoing AI cost).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sia.ai.client import LLMClient, Outcome
from sia.core.config import Effort
from sia.modules.companies.service import ENRICHABLE_FIELDS
from sia.modules.demo.dataset import SAMPLE_COMPANIES, SAMPLE_ICP, SampleCompany
from sia.modules.enrichment import extraction
from sia.modules.enrichment.fetcher import PageText
from sia.modules.enrichment.service import fill_values
from sia.modules.insights import briefs
from sia.modules.insights.service import score_facts
from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.engine import score_company
from sia.modules.scoring.service import build_facts

FORMAT_VERSION = 1


def base_record(company: SampleCompany) -> dict[str, Any]:
    """The company's own (non-AI) fields, as stored when sample data is loaded."""
    return {
        "name": company.name,
        "domain": company.domain,
        "website": company.website,
        "industry": company.industry,
        "employee_count": company.employee_count,
        "country": company.country,
        "city": company.city,
        "description": None,
    }


def apply_fill(record: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Same rule as companies.service.fill_empty_fields, on a plain dict."""
    filled = dict(record)
    for name, value in values.items():
        max_length = ENRICHABLE_FIELDS.get(name)
        if max_length is None or not value.strip() or filled.get(name) is not None:
            continue
        filled[name] = value.strip()[:max_length]
    return filled


def ordered_pages(company: SampleCompany) -> list[briefs.Page]:
    """Pages in the order the app reads them back (same fetch time, then by URL)."""
    pages = [briefs.Page(company.page_url(p), p.title, p.text) for p in company.pages]
    return sorted(pages, key=lambda p: p.url)


def brief_sources(
    company: SampleCompany, record: dict[str, Any], profile_facts: dict[str, Any] | None
) -> list[briefs.Source]:
    icp = ICPDefinition.model_validate(SAMPLE_ICP)
    result = score_company(
        icp, build_facts(SimpleNamespace(**record), profile_facts, len(company.contacts))
    )
    return briefs.build_sources(
        briefs.RecordFacts(**record),
        ordered_pages(company),
        score_facts(result.score, result.breakdown()),
        sorted({c.title for c in company.contacts}),
        len(company.contacts),
    )


async def build(
    profile_llm: LLMClient,
    brief_llm: LLMClient,
    *,
    profile_effort: Effort = "low",
    brief_effort: Effort = "medium",
) -> dict[str, Any]:
    companies: dict[str, Any] = {}
    now = datetime.now(UTC)
    for company in SAMPLE_COMPANIES:
        pages = [
            PageText(url=p.url, title=p.title, text=p.text, fetched_at=now)
            for p in ordered_pages(company)
        ]
        entry: dict[str, Any] = {"profile": None, "brief": None}
        extracted = await profile_llm.extract(
            system=extraction.SYSTEM_PROMPT,
            content=extraction.build_prompt(company.name, pages),
            output_type=extraction.ExtractedProfile,
            effort=profile_effort,
        )
        facts: dict[str, Any] | None = None
        if extracted.outcome is Outcome.SUCCESS and extracted.output is not None:
            verified = extraction.verify(extracted.output, pages)
            facts = verified.facts
            entry["profile"] = {
                "facts": facts,
                "kept": verified.kept,
                "dropped": verified.dropped,
                "model": extracted.model,
            }
        record = apply_fill(base_record(company), fill_values(facts or {}))
        sources = brief_sources(company, record, facts)
        written = await brief_llm.extract(
            system=briefs.SYSTEM_PROMPT,
            content=briefs.build_prompt(company.name, sources),
            output_type=briefs.BriefOutput,
            effort=brief_effort,
            max_tokens=8_000,
        )
        if written.outcome is Outcome.SUCCESS and written.output is not None:
            checked = briefs.verify(written.output, sources)
            entry["brief"] = {
                "content": checked.content,
                "kept": checked.kept,
                "dropped": checked.dropped,
                "model": written.model,
            }
        companies[company.domain] = entry
    return {
        "format_version": FORMAT_VERSION,
        "generated_at": now.isoformat(),
        "profile_prompt_version": extraction.PROMPT_VERSION,
        "brief_prompt_version": briefs.PROMPT_VERSION,
        "companies": companies,
    }
