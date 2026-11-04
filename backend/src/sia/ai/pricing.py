"""Cost estimates for Claude calls (USD per million tokens, Anthropic first-party API rates).

Estimates for dashboards and budgets, not invoices: the bill is authoritative. Update this table
when prices change; unknown models are costed at the most expensive known rate, so a missing
entry over-reports rather than hides spend.
"""

from dataclasses import dataclass
from decimal import Decimal

PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal  # 5-minute cache writes cost 1.25x input


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-sonnet-5-5": ModelPrice(Decimal("2"), Decimal("10"), Decimal("0.20"), Decimal("2.5")),
    # Haiku 5.5 prices apply to prompts up to 100K tokens (our prompts are far smaller).
    "claude-haiku-5-5": ModelPrice(
        Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")
    ),
}
_FALLBACK = max(PRICES.values(), key=lambda p: p.output)


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    price = PRICES.get(model, _FALLBACK)
    total = (
        price.input * input_tokens
        + price.output * output_tokens
        + price.cache_read * cache_read_tokens
        + price.cache_write * cache_write_tokens
    ) / PER_MILLION
    return total.quantize(Decimal("0.000001"))
