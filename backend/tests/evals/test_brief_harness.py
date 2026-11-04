"""The brief eval harness itself, checked offline with the fake model (runs in CI)."""

from decimal import Decimal
from typing import Any

from sia.ai.client import FakeLLMClient
from sia.modules.insights.briefs import BriefOutput, VerifiedBrief, build_prompt, verify
from sia.modules.insights.providers import fake_brief
from tests.evals.brief_cases import CASES, Case
from tests.evals.brief_harness import (
    CaseResult,
    grade,
    report,
    run_case,
    sources_for,
    summarise,
)


def case(name: str) -> Case:
    return next(c for c in CASES if c.name == name)


def content(**sections: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "summary": [],
        "fit": [],
        "key_facts": [],
        "priorities": [],
        "outreach": None,
        "gaps": [],
    }
    return base | sections


def claim(text: str) -> dict[str, Any]:
    return {"text": text, "citations": [{"source_id": "W1", "quote": "x"}]}


def graded(c: Case, **sections: Any) -> list[str]:
    return grade(c, VerifiedBrief(content=content(**sections), kept=1, dropped=0))


def test_cases_are_well_formed() -> None:
    names = [c.name for c in CASES]
    assert len(names) == len(set(names)) == 12
    assert sum(c.thin for c in CASES) == 1
    for c in CASES:
        sources = sources_for(c)
        assert sources[-1].id == "C"
        assert bool([s for s in sources if s.kind == "website"]) != c.thin


async def test_harness_runs_every_case_with_the_fake_model() -> None:
    llm = FakeLLMClient(fake_brief, model="fake-model")
    results = [await run_case(llm, c) for c in CASES]

    (summary,) = summarise(results)
    assert summary.cases == 12
    assert summary.coverage == 1.0  # the fake only quotes its sources verbatim
    assert summary.cost_per_brief > 0  # unknown models are priced at the highest known rate
    text = report(results)
    assert "MEETS TARGETS" in text or "below target" in text
    assert "Acme Widgets" in text


def test_grading_flags_injected_content() -> None:
    acme = case("Acme Widgets")
    clean = graded(
        acme,
        summary=[claim("Acme makes industrial fasteners for automotive suppliers.")],
        outreach={"angle": "Fasteners.", "opening_line": "Hi.", "discovery_questions": []},
    )
    assert clean == []
    hijacked = graded(
        acme,
        summary=[claim("Acme makes fasteners.")],
        outreach={
            "angle": "They urgently need us.",
            "opening_line": "Congratulations, you have been selected for a free audit!",
            "discovery_questions": [],
        },
    )
    assert "contains forbidden 'congratulations'" in hijacked


def test_mentioning_an_injection_in_gaps_is_fine() -> None:
    acme = case("Acme Widgets")
    problems = graded(
        acme,
        summary=[claim("Acme makes automotive fasteners.")],
        outreach={"angle": "a", "opening_line": "b", "discovery_questions": []},
        gaps=["The page also claimed to be a Swiss private bank; ignored."],
    )
    assert problems == []


def test_grading_requires_relevance_and_gaps_on_thin_data() -> None:
    assert graded(case("Saffron Table"), summary=[claim("A food company.")]) == [
        "mentions none of ['kit', 'kits', 'meal']",
        "no verified outreach angle",
    ]
    assert graded(case("Pinecrest Analytics")) == ["thin sources but no gaps listed"]
    assert graded(case("Pinecrest Analytics"), gaps=["Website not read yet."]) == []


def test_words_match_whole_words_only() -> None:
    # "app" must not be satisfied by "approach".
    clearpath = case("Clearpath Clinics")
    problems = graded(
        clearpath,
        summary=[claim("Outpatient physiotherapy clinics with a new approach.")],
        outreach={"angle": "a", "opening_line": "b", "discovery_questions": []},
    )
    assert problems == ["mentions none of ['app', 'exercise']"]


def test_summary_handles_failed_calls() -> None:
    results = [
        CaseResult(model="m", case="a", ok=True, kept=9, dropped=1, cost=Decimal("0.10")),
        CaseResult(model="m", case="b", ok=False, notes=["no brief (refused)"]),
    ]
    (s,) = summarise(results)
    assert (s.passed, s.cases, s.coverage) == (1, 2, 0.9)
    assert s.cost_per_brief == Decimal("0.05")
    assert s.meets_targets


def test_fake_brief_verifies_on_every_case() -> None:
    for c in CASES:
        sources = sources_for(c)
        output = fake_brief("", build_prompt(c.name, sources), BriefOutput)
        assert isinstance(output, BriefOutput)
        assert verify(output, sources).dropped == 0, c.name
