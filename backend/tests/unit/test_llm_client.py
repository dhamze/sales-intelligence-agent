"""The Claude client against a simulated API: request shape, parsing, refusals, errors."""

import json
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict

from sia.ai.client import FALLBACK_BETA, AnthropicLLMClient, Outcome


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str | None


def message(
    text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5"
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 300,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 0,
        },
    }


def client_returning(
    status: int, body: dict[str, Any], model: str = "claude-opus-5-5"
) -> tuple[AnthropicLLMClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body, headers={"request-id": "req_123"})

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    llm = AnthropicLLMClient(api_key="sk-test-not-real", model=model, http_client=http)
    llm._client = llm._client.with_options(max_retries=0)
    return llm, seen


async def extract(llm: AnthropicLLMClient) -> Any:
    return await llm.extract(
        system="Extract the city.", content="Acme is in Berlin.", output_type=Answer, effort="low"
    )


async def test_successful_extraction_and_request_shape() -> None:
    llm, seen = client_returning(200, message(json.dumps({"city": "Berlin"})))

    result = await extract(llm)

    assert result.outcome is Outcome.SUCCESS
    assert result.output == Answer(city="Berlin")
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (
        1200,
        300,
        1000,
    )
    assert result.request_id == "req_123"
    assert result.cost_usd > 0

    body = json.loads(seen[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"  # server-side refusal fallback opted in
    assert FALLBACK_BETA in seen[0].headers["anthropic-beta"]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"  # structured output
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in body  # removed in API version 2026-10-21


async def test_models_without_server_side_fallback_do_not_send_it() -> None:
    llm, seen = client_returning(
        200, message(json.dumps({"city": None}), model="claude-haiku-5-5"), model="claude-haiku-5-5"
    )

    await extract(llm)

    body = json.loads(seen[0].content)
    assert "fallbacks" not in body
    assert FALLBACK_BETA not in seen[0].headers.get("anthropic-beta", "")


async def test_refusal_is_reported_not_parsed() -> None:
    llm, _ = client_returning(200, message("", stop_reason="refusal"))

    result = await extract(llm)

    assert result.outcome is Outcome.REFUSED
    assert result.output is None
    assert result.input_tokens == 1200  # still logged and costed


async def test_truncated_output_is_incomplete() -> None:
    llm, _ = client_returning(200, message('{"city": "Ber', stop_reason="max_tokens"))

    result = await extract(llm)

    assert result.outcome is Outcome.INCOMPLETE


@pytest.mark.parametrize("status", [400, 429, 529])
async def test_api_errors_become_results_not_crashes(status: int) -> None:
    llm, _ = client_returning(
        status, {"type": "error", "error": {"type": "api_error", "message": "nope"}}
    )

    result = await extract(llm)

    assert result.outcome is Outcome.ERROR
    assert result.error == f"API error {status}"
