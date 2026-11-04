"""The scoring engine is pure, so every rule is pinned down here without a database."""

from typing import Any

import pytest
from pydantic import ValidationError

from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.engine import CompanyFacts, Status, score_company, tier_for


def icp(*criteria: dict[str, Any]) -> ICPDefinition:
    return ICPDefinition.model_validate({"criteria": list(criteria)})


def only(criterion: dict[str, Any], facts: CompanyFacts) -> tuple[Status, str]:
    result = score_company(icp(criterion), facts).results[0]
    return result.status, result.detail


SIZE_50_500 = {"kind": "size", "min_employees": 50, "max_employees": 500}


# --- tiers ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "tier"),
    [(100, "A"), (75, "A"), (74, "B"), (50, "B"), (49, "C"), (25, "C"), (24, "D"), (0, "D")],
)
def test_tier_boundaries(score: int, tier: str) -> None:
    assert tier_for(score) == tier


# --- individual criteria -------------------------------------------------------------------


def test_industry_matches_case_insensitively_and_prefers_user_data() -> None:
    criterion = {"kind": "industry", "industries": ["Software", "Fintech"]}
    assert only(criterion, CompanyFacts(industry="software"))[0] is Status.MATCH
    # The user's value wins over the AI's, even when the AI's would match.
    status, detail = only(criterion, CompanyFacts(industry="Retail", ai_industry="Software"))
    assert status is Status.MISS
    assert "Retail is not in your ICP" in detail


def test_industry_falls_back_to_verified_ai_value_and_says_so() -> None:
    criterion = {"kind": "industry", "industries": ["Software"]}
    status, detail = only(criterion, CompanyFacts(ai_industry="Software"))
    assert status is Status.MATCH
    assert "(from website)" in detail


def test_unknown_data_is_reported_as_unknown() -> None:
    criterion = {"kind": "industry", "industries": ["Software"]}
    status, detail = only(criterion, CompanyFacts())
    assert status is Status.UNKNOWN
    assert "enrich" in detail


@pytest.mark.parametrize(
    ("count", "status"),
    [(49, Status.MISS), (50, Status.MATCH), (500, Status.MATCH), (501, Status.MISS)],
)
def test_size_bounds_are_inclusive(count: int, status: Status) -> None:
    assert only(SIZE_50_500, CompanyFacts(employee_count=count))[0] is status


def test_size_with_only_a_minimum_has_no_upper_limit() -> None:
    criterion = {"kind": "size", "min_employees": 100}
    assert only(criterion, CompanyFacts(employee_count=1_000_000))[0] is Status.MATCH
    assert only(criterion, CompanyFacts(ai_employee_range="10000+"))[0] is Status.MATCH


@pytest.mark.parametrize(
    ("estimate", "status"),
    [
        ("51-200", Status.MATCH),  # entirely inside 50-500
        ("201-500", Status.MATCH),
        ("11-50", Status.PARTIAL),  # overlaps the lower bound
        ("501-1000", Status.MISS),  # entirely above
        ("1-10", Status.MISS),  # entirely below
        ("10000+", Status.MISS),
        ("201-1000", Status.PARTIAL),
        ("lots", Status.UNKNOWN),  # unparseable estimate
    ],
)
def test_size_from_ai_estimated_range(estimate: str, status: Status) -> None:
    assert only(SIZE_50_500, CompanyFacts(ai_employee_range=estimate))[0] is status


def test_open_ended_range_overlapping_a_capped_icp_is_partial() -> None:
    criterion = {"kind": "size", "max_employees": 5000}
    assert only(criterion, CompanyFacts(ai_employee_range="1000+"))[0] is Status.PARTIAL


def test_partial_match_earns_half_the_points() -> None:
    result = score_company(icp(SIZE_50_500), CompanyFacts(ai_employee_range="11-50"))
    assert result.results[0].points == 15
    assert result.score == 50


def test_exact_employee_count_beats_the_ai_estimate() -> None:
    facts = CompanyFacts(employee_count=10, ai_employee_range="51-200")
    assert only(SIZE_50_500, facts)[0] is Status.MISS


def test_country() -> None:
    criterion = {"kind": "country", "countries": ["DE", "AT", "CH"]}
    assert only(criterion, CompanyFacts(country="de"))[0] is Status.MATCH
    assert only(criterion, CompanyFacts(ai_country="CH"))[0] is Status.MATCH
    assert only(criterion, CompanyFacts(country="US"))[0] is Status.MISS


def test_business_model() -> None:
    criterion = {"kind": "business_model", "models": ["B2B", "B2B and B2C"]}
    assert only(criterion, CompanyFacts(ai_business_model="B2B"))[0] is Status.MATCH
    assert only(criterion, CompanyFacts(ai_business_model="B2C"))[0] is Status.MISS
    assert only(criterion, CompanyFacts())[0] is Status.UNKNOWN


def test_keywords_match_whole_words_and_quote_the_evidence() -> None:
    criterion = {"kind": "keywords", "keywords": ["payroll", "HR"]}
    facts = CompanyFacts(texts=[("description", "Cloud payroll for growing companies.")])
    status, detail = only(criterion, facts)
    assert status is Status.MATCH
    assert '"payroll" in description' in detail
    assert "Cloud payroll for growing companies." in detail
    # "HR" must not match inside "three".
    assert only(criterion, CompanyFacts(texts=[("description", "three apps")]))[0] is Status.MISS


def test_keywords_with_special_characters_are_matched_literally() -> None:
    criterion = {"kind": "keywords", "keywords": ["C++", "a.i"]}
    assert only(criterion, CompanyFacts(texts=[("x", "We write C++ tools")]))[0] is Status.MATCH
    assert only(criterion, CompanyFacts(texts=[("x", "aXi")]))[0] is Status.MISS


def test_keywords_without_any_text_are_unknown() -> None:
    criterion = {"kind": "keywords", "keywords": ["payroll"]}
    assert only(criterion, CompanyFacts(texts=[("description", "  ")]))[0] is Status.UNKNOWN


def test_long_keyword_evidence_is_shortened() -> None:
    criterion = {"kind": "keywords", "keywords": ["payroll"]}
    text = "x" * 200 + " payroll " + "y" * 200
    _, detail = only(criterion, CompanyFacts(texts=[("website", text)]))
    assert detail.count("...") == 2
    assert len(detail) < 150


def test_contacts() -> None:
    criterion = {"kind": "has_contacts", "min_contacts": 2}
    assert only(criterion, CompanyFacts(contact_count=2))[0] is Status.MATCH
    status, detail = only(criterion, CompanyFacts(contact_count=1))
    assert status is Status.MISS
    assert detail == "1 contact on file (your ICP: at least 2)"


# --- combining criteria --------------------------------------------------------------------

FULL_ICP = icp(
    {"kind": "industry", "industries": ["Software"], "importance": 5},
    {**SIZE_50_500, "importance": 3},
    {"kind": "country", "countries": ["DE"], "importance": 2},
)


def test_score_is_weighted_by_importance() -> None:
    # Industry (50) + country (20) of 100 possible points.
    facts = CompanyFacts(industry="Software", employee_count=5, country="DE")
    result = score_company(FULL_ICP, facts)
    assert result.score == 70
    assert result.tier == "B"
    assert result.completeness == 1.0


def test_perfect_fit_scores_100() -> None:
    facts = CompanyFacts(industry="Software", employee_count=100, country="DE")
    assert score_company(FULL_ICP, facts).score == 100


def test_missing_data_counts_as_no_match_and_lowers_completeness() -> None:
    result = score_company(FULL_ICP, CompanyFacts(industry="Software"))
    assert result.score == 50
    assert result.completeness == pytest.approx(0.33)
    assert [r.status for r in result.results] == [Status.MATCH, Status.UNKNOWN, Status.UNKNOWN]


def test_nothing_known_scores_zero() -> None:
    result = score_company(FULL_ICP, CompanyFacts())
    assert (result.score, result.tier, result.completeness) == (0, "D", 0.0)
    assert not result.disqualified


def test_failing_a_must_have_disqualifies() -> None:
    definition = icp(
        {"kind": "industry", "industries": ["Software"], "importance": 5},
        {"kind": "country", "countries": ["DE"], "importance": 1, "must_have": True},
    )
    result = score_company(definition, CompanyFacts(industry="Software", country="US"))
    assert result.disqualified
    assert (result.score, result.tier) == (0, "D")


def test_unknown_must_have_does_not_disqualify_but_is_flagged() -> None:
    definition = icp(
        {"kind": "industry", "industries": ["Software"], "importance": 5},
        {"kind": "country", "countries": ["DE"], "importance": 1, "must_have": True},
    )
    result = score_company(definition, CompanyFacts(industry="Software"))
    assert not result.disqualified
    assert result.score == 83
    assert "must-have, not yet checked" in result.results[1].detail


def test_scoring_is_deterministic() -> None:
    facts = CompanyFacts(industry="Software", ai_employee_range="11-50", country="DE")
    assert score_company(FULL_ICP, facts) == score_company(FULL_ICP, facts)


def test_breakdown_is_json_ready() -> None:
    result = score_company(FULL_ICP, CompanyFacts(industry="Software"))
    first = result.breakdown()[0]
    assert first == {
        "kind": "industry",
        "status": "match",
        "points": 50,
        "max_points": 50,
        "must_have": False,
        "detail": "Software is in your ICP (Software)",
    }
    assert type(first["status"]) is str


# --- ICP validation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "criteria",
    [
        [],  # at least one criterion
        [{"kind": "industry", "industries": ["A"]}, {"kind": "industry", "industries": ["B"]}],
        [{"kind": "size"}],  # needs a bound
        [{"kind": "size", "min_employees": 500, "max_employees": 50}],
        [{"kind": "industry", "industries": []}],
        [{"kind": "industry", "industries": ["A"], "importance": 6}],
        [{"kind": "industry", "industries": ["A"], "importance": 0}],
        [{"kind": "business_model", "models": ["Nonprofit"]}],
        [{"kind": "keywords", "keywords": ["a"]}],  # too short to be meaningful
        [{"kind": "industry", "industries": ["A"], "unexpected": 1}],
        [{"kind": "revenue"}],
    ],
)
def test_invalid_icps_are_rejected(criteria: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        ICPDefinition.model_validate({"criteria": criteria})


def test_icp_round_trips_through_json() -> None:
    restored = ICPDefinition.model_validate_json(FULL_ICP.model_dump_json())
    assert restored == FULL_ICP
