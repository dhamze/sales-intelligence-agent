"""Generate the sample data's AI content once (operator tool; costs real money).

    uv run python -m sia.scripts.build_sample_ai            # real models, ~$1-2 on Opus 5.5
    uv run python -m sia.scripts.build_sample_ai --fake --out <path>   # offline check

Uses ANTHROPIC_API_KEY and the configured models (SIA_ENRICHMENT_MODEL, SIA_BRIEF_MODEL).
Writes backend/src/sia/modules/demo/sample_ai.json by default; review it and commit it.
"""

import argparse
import asyncio
import json
from pathlib import Path

from sia.ai.client import AnthropicLLMClient, FakeLLMClient, LLMClient
from sia.core.config import get_settings
from sia.modules.demo import ai_build
from sia.modules.demo.service import SAMPLE_AI_PATH
from sia.modules.enrichment.providers import fake_profile
from sia.modules.insights.providers import fake_brief


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fake", action="store_true", help="use the offline fake models")
    parser.add_argument("--out", type=Path, default=SAMPLE_AI_PATH)
    args = parser.parse_args()
    settings = get_settings()

    profile_llm: LLMClient
    brief_llm: LLMClient
    if args.fake:
        profile_llm, brief_llm = FakeLLMClient(fake_profile), FakeLLMClient(fake_brief)
    else:
        if settings.anthropic_api_key is None:
            parser.error("ANTHROPIC_API_KEY is not set in .env")
        key = settings.anthropic_api_key.get_secret_value()
        profile_llm = AnthropicLLMClient(api_key=key, model=settings.enrichment_model)
        brief_llm = AnthropicLLMClient(api_key=key, model=settings.brief_model)
    try:
        data = await ai_build.build(
            profile_llm,
            brief_llm,
            profile_effort=settings.enrichment_effort,
            brief_effort=settings.brief_effort,
        )
    finally:
        for llm in (profile_llm, brief_llm):
            close = getattr(llm, "close", None)
            if close is not None:
                await close()

    entries = data["companies"].values()
    profiles = sum(1 for e in entries if e["profile"])
    briefs = sum(1 for e in entries if e["brief"])
    dropped = sum(e["brief"]["dropped"] for e in entries if e["brief"])
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}: {profiles} profiles, {briefs} briefs, {dropped} claims dropped.")


if __name__ == "__main__":
    asyncio.run(main())
