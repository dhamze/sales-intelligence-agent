"""enable postgres extensions

- vector  (pgvector): embedding storage and similarity search (semantic search, later phases).
- pg_trgm: trigram indexes for fast fuzzy / partial-match search on company names and domains.

Revision ID: 01f635221431
Revises:
Create Date: 2026-11-04 12:22:04.091965

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01f635221431"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
