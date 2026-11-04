"""LLM access behind a small interface (ADR-0006).

Application code depends on `LLMClient`, never on the SDK directly:
- `AnthropicLLMClient` calls Claude with structured outputs (the API guarantees the response
  matches the schema; the SDK validates it into a Pydantic object);
- `FakeLLMClient` returns scripted results for tests and offline demos.

Every call returns a `StructuredResult` that includes token usage and cost, including failed
and refused calls, so spending is always recorded.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import anthropic
import httpx2
import structlog
from anthropic import transform_schema
from pydantic import BaseModel, ValidationError

from sia.ai.pricing import estimate_cost
from sia.core.config import Effort

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Server-side refusal fallback ("default" routing by refusal category). Supported on the
# Opus/Sonnet 5.x family on the Claude API; Haiku has no server-side fallback.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"})


class Outcome(StrEnum):
    SUCCESS = "success"
    REFUSED = "refused"  # safety decline (after any fallback)
    INCOMPLETE = "incomplete"  # ran out of tokens / no parsable output
    ERROR = "error"  # API or network failure after the SDK's retries


@dataclass(frozen=True)
class StructuredResult[OutT]:
    outcome: Outcome
    output: OutT | None
    model: str  # the model that actually answered (may differ after a fallback)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None
    stop_reason: str | None = None
    error: str | None = None

    @property
    def cost_usd(self) -> Decimal:
        return estimate_cost(
            self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
        )


class LLMClient(Protocol):
    model: str

    async def extract(
        self,
        *,
        system: str,
        content: str,
        output_type: type[T],
        effort: Effort,
        max_tokens: int = 16_000,
    ) -> StructuredResult[T]: ...


class AnthropicLLMClient:
    def __init__(
        self, *, api_key: str, model: str, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        self.model = model
        # The SDK retries rate limits, 5xx and connection errors (2 retries by default).
        # `http_client` lets tests substitute a simulated network.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=120.0, http_client=http_client
        )

    async def close(self) -> None:
        await self._client.close()

    async def extract(
        self,
        *,
        system: str,
        content: str,
        output_type: type[T],
        effort: Effort,
        max_tokens: int = 16_000,
    ) -> StructuredResult[T]:
        options: dict[str, Any] = {}
        if self.model in FALLBACK_MODELS:
            options = {"fallbacks": "default", "betas": [FALLBACK_BETA]}
        started = time.monotonic()
        try:
            # create() + our own validation (rather than parse()): parse() raises on truncated or
            # invalid output before returning, which would lose the usage - i.e. unlogged spend.
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": transform_schema(output_type)},
                },
                **options,
            )
        except anthropic.APIStatusError as exc:
            logger.warning("llm_call_failed", status=exc.status_code, request_id=exc.request_id)
            return StructuredResult(
                outcome=Outcome.ERROR,
                output=None,
                model=self.model,
                latency_ms=_ms_since(started),
                request_id=exc.request_id,
                error=f"API error {exc.status_code}",
            )
        except anthropic.APIConnectionError as exc:
            logger.warning("llm_call_failed", error=type(exc).__name__)
            return StructuredResult(
                outcome=Outcome.ERROR,
                output=None,
                model=self.model,
                latency_ms=_ms_since(started),
                error=type(exc).__name__,
            )

        output: T | None = None
        error: str | None = None
        if response.stop_reason == "refusal":
            outcome = Outcome.REFUSED
        else:
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                output = output_type.model_validate_json(text)
                outcome = Outcome.SUCCESS
            except ValidationError as exc:
                outcome = Outcome.INCOMPLETE  # cut off (max_tokens) or not valid for the schema
                error = f"Invalid output: {exc.error_count()} validation error(s)"
        usage = response.usage
        return StructuredResult(
            outcome=outcome,
            output=output,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            latency_ms=_ms_since(started),
            request_id=response._request_id,
            stop_reason=response.stop_reason,
            error=error,
        )


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class FakeLLMClient:
    """Scripted responses: `respond(system, content, output_type)` builds the output.
    Records every call so tests can inspect prompts."""

    def __init__(
        self,
        respond: Callable[[str, str, type[Any]], BaseModel | None],
        model: str = "fake-model",
    ) -> None:
        self.model = model
        self._respond = respond
        self.calls: list[tuple[str, str]] = []

    async def extract(
        self,
        *,
        system: str,
        content: str,
        output_type: type[T],
        effort: Effort,
        max_tokens: int = 16_000,
    ) -> StructuredResult[T]:
        self.calls.append((system, content))
        output = self._respond(system, content, output_type)
        if output is not None and not isinstance(output, output_type):
            raise TypeError(f"Fake returned {type(output).__name__}, expected {output_type}")
        return StructuredResult(
            outcome=Outcome.SUCCESS if output is not None else Outcome.INCOMPLETE,
            output=output,
            model=self.model,
            input_tokens=len(system + content) // 4,
            output_tokens=200,
        )


def summarise_usage(results: Sequence[StructuredResult[Any]]) -> dict[str, Any]:
    return {
        "calls": len(results),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "cost_usd": str(sum((r.cost_usd for r in results), Decimal(0))),
    }
