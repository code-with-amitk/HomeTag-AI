"""
> Why: Provide request-scoped SQLAlchemy sessions with deterministic cleanup.
> Throughput: One session per API request, backed by the configured connection pool.
> Dependencies: SQLAlchemy sessionmaker and FastAPI request state.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    """Yield a session from the application session factory."""
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session
