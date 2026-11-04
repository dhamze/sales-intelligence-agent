"""job queue

Procrastinate's tables, types and functions (PostgreSQL-backed job queue, ADR-0002), applied
from a frozen copy of its schema, plus privileges for the runtime role, which both enqueues
jobs (API) and runs them (worker).

These tables are infrastructure, not tenant data: job arguments carry only IDs, and every
job opens a tenant-scoped session (RLS) before touching customer data.

Revision ID: c475e57bd0f6
Revises: f3abc476c39f
Create Date: 2026-11-04 14:38:00

"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_

from sia.core.config import APP_DB_ROLE

# revision identifiers, used by Alembic.
revision: str = "c475e57bd0f6"
down_revision: str | Sequence[str] | None = "f3abc476c39f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "sql" / "procrastinate_3.10.0_schema.sql"

TABLES = (
    "procrastinate_workers",
    "procrastinate_jobs",
    "procrastinate_periodic_defers",
    "procrastinate_events",
)
SEQUENCES = (
    "procrastinate_jobs_id_seq",
    "procrastinate_periodic_defers_id_seq",
    "procrastinate_events_id_seq",
)


def upgrade() -> None:
    # A multi-statement script with PL/pgSQL bodies can't go through a prepared statement, so
    # it runs via asyncpg's simple query protocol, inside the migration's transaction.
    driver_connection = op.get_bind().connection.dbapi_connection.driver_connection  # type: ignore[union-attr]
    await_(driver_connection.execute(SCHEMA_FILE.read_text(encoding="utf-8")))
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {APP_DB_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {', '.join(SEQUENCES)} TO {APP_DB_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP TABLE {', '.join(reversed(TABLES))} CASCADE")
    op.execute(
        """
        DO $$
        DECLARE f record;
        BEGIN
            FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
                     JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE 'DROP FUNCTION ' || f.sig || ' CASCADE';
            END LOOP;
        END $$
        """
    )
    op.execute(
        "DROP TYPE procrastinate_job_to_defer_v1, procrastinate_job_event_type, "
        "procrastinate_job_status"
    )
