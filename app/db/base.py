"""
> Why: Provide the shared SQLAlchemy declarative metadata for application entities.
> Throughput: Imported during startup and migration generation, not on request paths.
> Dependencies: SQLAlchemy 2.x.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for typed SQLAlchemy models."""
