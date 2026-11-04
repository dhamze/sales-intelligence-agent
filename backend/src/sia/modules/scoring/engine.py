"""The scoring engine: a pure function from (ICP, company facts) to a score with a breakdown.

No database, no network, no randomness: the same inputs always give the same score, every point
is traceable to one criterion, and the whole engine can be tested exhaustively (ADR-0011).

Rules:
- Each criterion is worth `importance x 10` points. A match earns all of them, a partial match
  (an estimated size range that only overlaps the ICP range) half, a miss or unknown none.
- Missing data scores like a miss but is reported as "unknown" (conservative: a company we know
  nothing about must not look like a perfect fit), with the share of known criteria reported
  as data completeness.
- Failing a must-have criterion disqualifies the company (score 0). An unknown must-have does not
  disqualify; it is flagged.
- Score = round(100 x earned / possible). Tiers: A >= 75, B >= 50, C >= 25, else D.
"""

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

from sia.modules.scoring.countries import same_country
from sia.modules.scoring.criteria import (
    BusinessModelCriterion,
    ContactsCriterion,
    CountryCriterion,
    Criterion,
    ICPDefinition,
    IndustryCriterion,
    KeywordCriterion,
    SizeCriterion,
)

Tier = Literal["A", "B", "C", "D"]
POINTS_PER_IMPORTANCE = 10


class Status(StrEnum):
    MATCH = "match"
    PARTIAL = "partial"
    MISS = "miss"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CompanyFacts:
    """Everything scoring may look at. `ai_*` values come from VERIFIED enrichment facts."""

    industry: str | None = None
    ai_industry: str | None = None
    employee_count: int | None = None
    ai_employee_range: str | None = None  # e.g. "51-200", "10000+"
    country: str | None = None
    ai_country: str | None = None
    ai_business_model: str | None = None
    texts: list[tuple[str, str]] = field(default_factory=list)  # (where, text) for keywords
    contact_count: int = 0


@dataclass(frozen=True)
class CriterionResult:
    kind: str
    status: Status
    points: float
    max_points: int
    must_have: bool
    detail: str


@dataclass(frozen=True)
class ScoreResult:
    score: int
    tier: Tier
    disqualified: bool
    completeness: float  # share of criteria whose data is known, 0..1
    results: list[CriterionResult]

    def breakdown(self) -> list[dict[str, Any]]:
        return [asdict(r) | {"status": r.status.value} for r in self.results]


def tier_for(score: int) -> Tier:
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _pick(user_value: str | None, ai_value: str | None) -> tuple[str | None, str]:
    """User-entered data wins; AI-extracted (verified) data fills the gap."""
    if user_value:
        return user_value, ""
    if ai_value:
        return ai_value, " (from website)"
    return None, ""


def _join(values: list[str]) -> str:
    return ", ".join(values)


def _industry(c: IndustryCriterion, f: CompanyFacts) -> tuple[Status, str]:
    value, source = _pick(f.industry, f.ai_industry)
    if value is None:
        return Status.UNKNOWN, "Industry unknown (enrich to fill in)"
    if any(_same(value, wanted) for wanted in c.industries):
        return Status.MATCH, f"{value}{source} is in your ICP ({_join(c.industries)})"
    return Status.MISS, f"{value}{source} is not in your ICP ({_join(c.industries)})"


_RANGE = re.compile(r"^(\d+)-(\d+)$|^(\d+)\+$")


def _parse_range(text: str) -> tuple[int, int | None] | None:
    m = _RANGE.match(text.strip())
    if not m:
        return None
    if m.group(3):
        return int(m.group(3)), None
    return int(m.group(1)), int(m.group(2))


def _size_text(c: SizeCriterion) -> str:
    if c.min_employees is not None and c.max_employees is not None:
        return f"{c.min_employees:,}-{c.max_employees:,}"
    if c.min_employees is not None:
        return f"{c.min_employees:,}+"
    return f"up to {c.max_employees:,}"


def _size(c: SizeCriterion, f: CompanyFacts) -> tuple[Status, str]:
    low_ok = c.min_employees if c.min_employees is not None else 0
    high_ok = c.max_employees  # None = no upper limit
    wanted = _size_text(c)
    if f.employee_count is not None:
        n = f.employee_count
        inside = n >= low_ok and (high_ok is None or n <= high_ok)
        status = Status.MATCH if inside else Status.MISS
        verb = "within" if inside else "outside"
        return status, f"{n:,} employees is {verb} your ICP ({wanted})"
    parsed = _parse_range(f.ai_employee_range) if f.ai_employee_range else None
    if parsed is None:
        return Status.UNKNOWN, "Employee count unknown (enrich to fill in)"
    low, high = parsed
    shown = f"{f.ai_employee_range} employees (from website)"
    fully_inside = low >= low_ok and high is not None and (high_ok is None or high <= high_ok)
    if high_ok is None and low >= low_ok:
        fully_inside = True
    disjoint = (high is not None and high < low_ok) or (high_ok is not None and low > high_ok)
    if fully_inside:
        return Status.MATCH, f"{shown} is within your ICP ({wanted})"
    if disjoint:
        return Status.MISS, f"{shown} is outside your ICP ({wanted})"
    return Status.PARTIAL, f"{shown} partly overlaps your ICP ({wanted})"


def _country(c: CountryCriterion, f: CompanyFacts) -> tuple[Status, str]:
    value, source = _pick(f.country, f.ai_country)
    if value is None:
        return Status.UNKNOWN, "Country unknown (enrich to fill in)"
    if any(same_country(value, wanted) for wanted in c.countries):
        return Status.MATCH, f"{value}{source} is in your ICP ({_join(c.countries)})"
    return Status.MISS, f"{value}{source} is not in your ICP ({_join(c.countries)})"


def _business_model(c: BusinessModelCriterion, f: CompanyFacts) -> tuple[Status, str]:
    if f.ai_business_model is None:
        return Status.UNKNOWN, "Business model unknown (enrich to fill in)"
    wanted = _join(list(c.models))
    if f.ai_business_model in c.models:
        return Status.MATCH, f"{f.ai_business_model} (from website) is in your ICP ({wanted})"
    return Status.MISS, f"{f.ai_business_model} (from website) is not in your ICP ({wanted})"


def _snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right].strip()}{suffix}"


def _keywords(c: KeywordCriterion, f: CompanyFacts) -> tuple[Status, str]:
    texts = [(where, text) for where, text in f.texts if text.strip()]
    if not texts:
        return Status.UNKNOWN, "No description or website facts to search (enrich to fill in)"
    for keyword in c.keywords:
        pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)", re.IGNORECASE)
        for where, text in texts:
            m = pattern.search(text)
            if m:
                return (
                    Status.MATCH,
                    f'"{keyword}" in {where}: "{_snippet(text, m.start(), m.end())}"',
                )
    return Status.MISS, f"None of your keywords found ({_join(c.keywords)})"


def _contacts(c: ContactsCriterion, f: CompanyFacts) -> tuple[Status, str]:
    plural = "contact" if f.contact_count == 1 else "contacts"
    if f.contact_count >= c.min_contacts:
        return Status.MATCH, f"{f.contact_count} {plural} on file"
    return Status.MISS, f"{f.contact_count} {plural} on file (your ICP: at least {c.min_contacts})"


_CHECKS = {
    "industry": _industry,
    "size": _size,
    "country": _country,
    "business_model": _business_model,
    "keywords": _keywords,
    "has_contacts": _contacts,
}


def _evaluate(criterion: Criterion, facts: CompanyFacts) -> CriterionResult:
    status, detail = _CHECKS[criterion.kind](criterion, facts)  # type: ignore[operator]
    max_points = criterion.importance * POINTS_PER_IMPORTANCE
    points = {Status.MATCH: max_points, Status.PARTIAL: max_points / 2}.get(status, 0)
    if criterion.must_have and status is Status.UNKNOWN:
        detail += " - must-have, not yet checked"
    return CriterionResult(
        kind=criterion.kind,
        status=status,
        points=points,
        max_points=max_points,
        must_have=criterion.must_have,
        detail=detail,
    )


def score_company(icp: ICPDefinition, facts: CompanyFacts) -> ScoreResult:
    results = [_evaluate(c, facts) for c in icp.criteria]
    disqualified = any(r.must_have and r.status is Status.MISS for r in results)
    possible = sum(r.max_points for r in results)
    earned = sum(r.points for r in results)
    score = 0 if disqualified or possible == 0 else round(100 * earned / possible)
    known = sum(r.status is not Status.UNKNOWN for r in results)
    return ScoreResult(
        score=score,
        tier=tier_for(score),
        disqualified=disqualified,
        completeness=round(known / len(results), 2) if results else 0.0,
        results=results,
    )
