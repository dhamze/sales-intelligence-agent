"""Rate limit counters. Not tenant data: keys are hashed client IPs, so no RLS (and no
organisation column)."""

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base


class RateLimitHit(Base):
    """Requests counted per key (rule + hashed client IP) per fixed time window."""

    __tablename__ = "rate_limit_hits"
    # UNLOGGED: faster writes, and losing counters in a database crash is harmless.
    __table_args__ = ({"prefixes": ["UNLOGGED"]},)

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
