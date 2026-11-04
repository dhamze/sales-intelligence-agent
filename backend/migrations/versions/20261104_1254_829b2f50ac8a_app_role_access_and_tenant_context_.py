"""app role access and tenant context functions

- Lets the restricted runtime role `sia_app` use the schema (table privileges are granted per
  table, in the migration that creates each table).
- Adds app_current_org_id() / app_current_user_id(), which RLS policies use to read the
  request's tenant context. See sia/core/tenancy.py and docs/adr/0007.

Requires the `sia_app` role to exist (infra/postgres/init/02-create-app-role.sh).

Revision ID: 829b2f50ac8a
Revises: 01f635221431
Create Date: 2026-11-04 12:54:00

"""

from collections.abc import Sequence

from alembic import op

from sia.core.config import APP_DB_ROLE
from sia.core.tenancy import context_functions_sql, drop_context_functions_sql

# revision identifiers, used by Alembic.
revision: str = "829b2f50ac8a"
down_revision: str | Sequence[str] | None = "01f635221431"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_DB_ROLE}")
    for statement in context_functions_sql():
        op.execute(statement)


def downgrade() -> None:
    for statement in drop_context_functions_sql():
        op.execute(statement)
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_DB_ROLE}")
