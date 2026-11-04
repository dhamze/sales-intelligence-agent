"""Registry of every ORM model, so Alembic autogenerate (and the drift check test) sees all tables.

When a module adds a `models.py`, import it here.
"""

from sia.modules.identity import models as identity_models

__all__ = ["identity_models"]
