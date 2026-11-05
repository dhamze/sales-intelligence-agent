"""Structured logging.

Every log line is a set of key/value pairs (an "event" plus context such as `request_id`).
In development they render as readable coloured text; in production as one JSON object per
line, which log platforms can search and filter.

Logs from third-party libraries (uvicorn, SQLAlchemy, ...) that use Python's standard `logging`
module are routed through the same pipeline so the output is consistent.
"""

import logging
import sys

import structlog
from structlog.typing import Processor

from sia.core.config import LogFormat, LogLevel
from sia.core.observability import forward_errors_to_sentry


def configure_logging(level: LogLevel, fmt: LogFormat) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # adds request_id etc. bound per request
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        forward_errors_to_sentry,  # no-op unless Sentry is configured (see observability.py)
    ]

    renderer: Processor
    if fmt == "json":
        renderer = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.dict_tracebacks)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    # We log each request ourselves (with request_id and duration), so silence the duplicate.
    logging.getLogger("uvicorn.access").disabled = True
