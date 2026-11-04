"""Registry of every ORM model, so Alembic autogenerate (and the drift check test) sees all tables.

When a module adds a `models.py`, import it here.
"""

from sia.ai import models as ai_models
from sia.modules.companies import models as companies_models
from sia.modules.contacts import models as contacts_models
from sia.modules.enrichment import models as enrichment_models
from sia.modules.identity import models as identity_models
from sia.modules.imports import models as imports_models

__all__ = [
    "ai_models",
    "companies_models",
    "contacts_models",
    "enrichment_models",
    "identity_models",
    "imports_models",
]
