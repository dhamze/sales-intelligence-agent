import base64
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, DateTime, Float, String

from sia.core.pagination import InvalidCursorError, SortSpec, decode_cursor, encode_cursor

BY_NAME = SortSpec(key="name", column=Column("name", String), descending=False, value_type=str)
BY_DATE = SortSpec(
    key="-created_at",
    column=Column("created_at", DateTime(timezone=True)),
    descending=True,
    value_type=datetime,
)
BY_SCORE = SortSpec(key="relevance", column=Column("r", Float), descending=True, value_type=float)


@pytest.mark.parametrize(
    ("spec", "value"),
    [
        (BY_NAME, "Acme Ünïcode"),
        (BY_DATE, datetime(2026, 11, 4, 12, 30, 15, 123456, tzinfo=UTC)),
        (BY_SCORE, 0.6666666865348816),  # float4 similarity values must round-trip exactly
    ],
)
def test_cursor_round_trip(spec: SortSpec, value: object) -> None:
    row_id = uuid.uuid4()

    cursor = encode_cursor(spec, value, row_id)

    assert decode_cursor(cursor, spec) == (value, row_id)
    assert "=" not in cursor  # URL-safe, unpadded


def _forge(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!",
        _forge("just a string"),
        _forge({"s": "name", "v": "x"}),  # missing id
        _forge({"s": "name", "v": "x", "id": "not-a-uuid"}),
        _forge({"s": "-created_at", "v": "x", "id": str(uuid.uuid4())}),  # other sort's cursor
        _forge({"s": "name", "v": {"$gt": ""}, "id": str(uuid.uuid4())}),  # wrong value type
        "A" * 2000,
    ],
)
def test_malformed_or_mismatched_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor, BY_NAME)


def test_date_cursor_rejects_non_date_value() -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(
            _forge({"s": "-created_at", "v": "yesterday", "id": str(uuid.uuid4())}), BY_DATE
        )
