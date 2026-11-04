"""Live AI quality check for account briefs: choose the model with data.

    uv run pytest backend/tests/evals/test_briefs_live.py --run-live-llm -s

Costs real money (about $1-2 for 12 briefs on Opus 5.5, cents on Haiku 5.5) and needs
ANTHROPIC_API_KEY in .env. Never runs in CI. Uses the fixed, fictional cases in brief_cases.py,
so results are comparable across models and over time. Prints a comparison table.

Models: SIA_EVAL_MODELS (comma-separated), default "claude-opus-5-5,claude-haiku-5-5".
Effort: SIA_BRIEF_EFFORT from .env (default "medium").
"""

import os

import pytest

from sia.ai.client import AnthropicLLMClient
from sia.core.config import Settings
from tests.evals.brief_cases import CASES
from tests.evals.brief_harness import CaseResult, report, run_case, summarise

pytestmark = pytest.mark.live_llm


@pytest.fixture(scope="module")
def settings() -> Settings:
    s = Settings()
    if s.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    return s


async def test_compare_models_on_briefs(settings: Settings) -> None:
    assert settings.anthropic_api_key is not None
    raw = os.environ.get("SIA_EVAL_MODELS", "claude-opus-5-5,claude-haiku-5-5")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    results: list[CaseResult] = []
    for model in models:
        llm = AnthropicLLMClient(api_key=settings.anthropic_api_key.get_secret_value(), model=model)
        try:
            for case in CASES:
                results.append(await run_case(llm, case, settings.brief_effort))
        finally:
            await llm.close()

    print("\n\n" + report(results))
    # Product requirement (docs/product.md): >= 90% of claims carry a valid citation, and no
    # model may follow instructions planted in a website.
    failing = [s.model for s in summarise(results) if not s.meets_targets]
    assert not failing, f"below target: {failing}"
