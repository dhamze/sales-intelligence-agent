"""Request/response models for imports."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sia.modules.imports.mapping import EntityType
from sia.modules.imports.models import ImportStatus


class RowErrorOut(BaseModel):
    row: int = Field(description="Line number in the uploaded file")
    field: str | None
    message: str


class ImportOut(BaseModel):
    """An import's state and results (for previews, counts describe what WOULD happen)."""

    id: uuid.UUID
    entity_type: EntityType
    status: ImportStatus
    filename: str
    row_count: int
    headers: list[str]
    mapping: dict[str, str | None]
    created_count: int = Field(description="New records (completed imports)")
    updated_count: int = Field(description="Existing records whose empty fields were filled")
    unchanged_count: int = Field(description="Valid rows that matched and changed nothing")
    invalid_count: int
    duplicate_count: int = Field(description="Rows repeating an earlier row in the same file")
    errors: list[RowErrorOut]
    created_at: datetime
    completed_at: datetime | None


class ImportPreview(ImportOut):
    available_fields: list[str] = Field(description="Valid mapping targets for this entity type")
    sample_rows: list[dict[str, str]] = Field(description="First rows, as header -> value")
    valid_count: int = Field(description="Rows that will be imported")
    existing_matches: int = Field(description="Valid rows matching an existing record (merge)")
    encoding: str
    delimiter: str


class CommitImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: dict[str, str | None] | None = Field(
        default=None,
        description="Optional corrected mapping {csv header: field, 'attributes', or null}",
    )
