"""Background worker (Procrastinate, ADR-0002).

    uv run python -m sia.worker

Jobs are enqueued with `sia.core.jobs.enqueue()` inside the caller's transaction. The worker
connects as the restricted runtime role `sia_app` and runs each job's database work in a
tenant-scoped session (`sia.worker.runtime.tenant_session`), so Row-Level Security applies to
background work exactly as it does to API requests.

Tasks are registered on `app` by the modules listed in `TASK_MODULES`.
"""

import procrastinate
from psycopg.conninfo import make_conninfo

from sia.core.config import APP_DB_ROLE, Settings

TASK_MODULES = ["sia.worker.tasks"]

# Tasks register against this app at import time. Its connector is a placeholder:
# `configured_app()` returns a copy connected with real settings.
app = procrastinate.App(connector=procrastinate.PsycopgConnector(), import_paths=TASK_MODULES)


def conninfo(settings: Settings) -> str:
    """libpq connection string for the runtime role (make_conninfo escapes every value)."""
    return make_conninfo(
        host=settings.postgres_host,
        port=str(settings.postgres_port),
        dbname=settings.postgres_db,
        user=APP_DB_ROLE,
        password=settings.app_db_password.get_secret_value(),
        application_name=f"sia-worker-{settings.env}",
        connect_timeout=str(int(settings.db_connect_timeout_seconds)),
    )


def configured_app(settings: Settings) -> procrastinate.App:
    connector = procrastinate.PsycopgConnector(
        conninfo=conninfo(settings), min_size=1, max_size=settings.worker_concurrency + 2
    )
    return app.with_connector(connector)
