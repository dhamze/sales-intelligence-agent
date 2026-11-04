"""Reusable Pydantic field types.

Optional text fields accept "" or whitespace (as sent by forms and CSV files) and store NULL.
The length limit is attached to the `str` member of the union, not to the union itself:
a constraint on `str | None` would also be applied to `None` (and crash measuring len(None)).
"""

from typing import Annotated, Any

from pydantic import BeforeValidator, StringConstraints


def blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


BlankToNone = BeforeValidator(blank_to_none)

OptionalTinyText = Annotated[Annotated[str, StringConstraints(max_length=50)] | None, BlankToNone]
OptionalShortText = Annotated[Annotated[str, StringConstraints(max_length=100)] | None, BlankToNone]
OptionalMediumText = Annotated[
    Annotated[str, StringConstraints(max_length=200)] | None, BlankToNone
]
OptionalLongText = Annotated[Annotated[str, StringConstraints(max_length=5000)] | None, BlankToNone]
OptionalUnboundedInput = Annotated[str | None, BlankToNone]  # validated/normalised elsewhere
