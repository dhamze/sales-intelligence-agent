"""Shared helpers for fuzzy text search with pg_trgm.

`q <% column` is true when some run of words in `column` is similar enough to `q`
(word_similarity >= pg_trgm.word_similarity_threshold). It is served by GIN trigram indexes.

The default threshold (0.6) misses ordinary typos in short names: "micheal bolton" vs
"Michael Bolton" scores 0.58. We lower it to 0.5 for the current transaction only; results are
ranked by similarity, so weaker matches appear last rather than displacing good ones.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WORD_SIMILARITY_THRESHOLD = 0.5


async def use_search_threshold(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT set_config('pg_trgm.word_similarity_threshold', :value, true)"),
        {"value": str(WORD_SIMILARITY_THRESHOLD)},
    )


def escape_like(value: str) -> str:
    """Make user input literal inside LIKE/ILIKE patterns (`%` and `_` are wildcards)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
