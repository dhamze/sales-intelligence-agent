"""Cursor-based ("keyset") pagination.

Why not page numbers (OFFSET)? With OFFSET, rows inserted or deleted between requests make
pages skip or repeat rows, and the database must still read and discard every skipped row, so
deep pages get slower and slower. A keyset cursor instead says "continue after the row whose
(sort value, id) is X": stable while data changes, and an index seek at any depth.

The cursor is opaque to clients (base64 JSON) but not secret: it only positions the query
within the caller's own, already-filtered and tenant-scoped results. Malformed or mismatched
cursors are rejected with 400 `invalid_cursor`.
"""

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import ColumnElement, literal, tuple_
from sqlalchemy.orm import InstrumentedAttribute

from sia.core.errors import AppError

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
_MAX_CURSOR_LENGTH = 1024


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class InvalidCursorError(AppError):
    status_code = 400
    code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("The pagination cursor is invalid. Restart from the first page.")


@dataclass(frozen=True)
class SortSpec:
    """How a list is ordered. `key` is the public name (e.g. "-name"); rows are always
    tie-broken by `id` in the same direction, so the order is total and deterministic."""

    key: str
    column: ColumnElement[Any] | InstrumentedAttribute[Any]
    descending: bool
    value_type: type


def encode_cursor(spec: SortSpec, value: Any, row_id: uuid.UUID) -> str:
    if isinstance(value, datetime):
        value = value.isoformat()
    payload = json.dumps({"s": spec.key, "v": value, "id": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, spec: SortSpec) -> tuple[Any, uuid.UUID]:
    if len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursorError()
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("s") != spec.key:
            raise InvalidCursorError()  # cursor from a different sort order
        value: Any = TypeAdapter(spec.value_type).validate_python(payload["v"])
        return value, uuid.UUID(payload["id"])
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError, ValidationError):
        raise InvalidCursorError() from None


def keyset_condition(
    spec: SortSpec, id_column: InstrumentedAttribute[uuid.UUID], after: tuple[Any, uuid.UUID]
) -> ColumnElement[bool]:
    """Rows strictly after `after` in the sort order: (sort, id) > / < (value, id)."""
    value, row_id = after
    left = tuple_(spec.column, id_column)
    right = tuple_(literal(value, spec.column.type), literal(row_id, id_column.type))
    return left < right if spec.descending else left > right


def order_by(
    spec: SortSpec, id_column: InstrumentedAttribute[uuid.UUID]
) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    if spec.descending:
        return spec.column.desc(), id_column.desc()
    return spec.column.asc(), id_column.asc()


def build_page(
    rows: Sequence[tuple[Any, Any]], limit: int, spec: SortSpec, to_item: Any, get_id: Any
) -> Page[Any]:
    """`rows` were fetched with LIMIT limit+1 as (entity, sort_value) pairs; the extra row only
    tells us whether another page exists."""
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        entity, sort_value = rows[-1]
        next_cursor = encode_cursor(spec, sort_value, get_id(entity))
    return Page(items=[to_item(entity) for entity, _ in rows], next_cursor=next_cursor)
