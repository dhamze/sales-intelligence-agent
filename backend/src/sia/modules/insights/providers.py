"""Where briefs get their AI answers from: Claude, or a deterministic fake for tests and demos
(refused in production by Settings)."""

import re
from typing import Any
from xml.sax.saxutils import unescape

from pydantic import BaseModel

from sia.ai.client import AnthropicLLMClient, FakeLLMClient, LLMClient
from sia.core.config import Settings
from sia.core.errors import AppError
from sia.modules.insights.briefs import BriefOutput, Citation, Claim, Outreach


class BriefsUnavailableError(AppError):
    status_code = 503
    code = "briefs_unavailable"

    def __init__(self) -> None:
        super().__init__("AI briefs are not configured on this server.")


_SOURCE = re.compile(r'<source id="(?P<id>[^"]+)"[^>]*>\n(?P<text>.*?)\n</source>', re.DOTALL)


def _sources(content: str) -> dict[str, str]:
    return {m["id"]: unescape(m["text"]) for m in _SOURCE.finditer(content)}


def _opening(text: str, words: int = 12) -> str:
    """The first few words of a text: a quote that certainly occurs in it."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return " ".join(first_line.split()[:words])


def fake_brief(_system: str, content: str, _output_type: type[Any]) -> BaseModel:
    """A brief citing the prompt's own sources verbatim, so every citation verifies."""
    sources = _sources(content)
    web = [sid for sid in sources if sid.startswith("W")]
    main = web[0] if web else "R"

    def claim(text: str, source_id: str) -> Claim:
        return Claim(
            text=text,
            citations=[Citation(source_id=source_id, quote=_opening(sources[source_id]))],
        )

    fit = (
        [claim("The company's ICP fit is summarised in the score.", "S")] if "S" in sources else []
    )
    return BriefOutput(
        summary=[claim(f"Summary based on {main}: {_opening(sources[main], 20)}", main)],
        fit=fit,
        key_facts=[claim(f"From {sid}: {_opening(sources[sid], 20)}", sid) for sid in sources][:6],
        priorities=[claim("They likely want to reduce manual work.", main)],
        outreach=Outreach(
            angle="Lead with how teams like theirs cut manual reporting work.",
            opening_line="I noticed your team's focus on automation and had a quick question.",
            discovery_questions=[
                "How do you handle month-end reporting today?",
                "What would you change about it first?",
            ],
            citations=[Citation(source_id=main, quote=_opening(sources[main]))],
        ),
        gaps=["Budget and buying timeline are not stated."],
    )


def make_brief_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLMClient(fake_brief, model="fake-model")
    if settings.anthropic_api_key is None:
        raise BriefsUnavailableError()
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(), model=settings.brief_model
    )
