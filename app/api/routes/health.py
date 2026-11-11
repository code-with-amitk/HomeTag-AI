"""
> Why: Expose liveness and dependency-readiness checks for the API runtime.
> Throughput: Lightweight probes; readiness performs one database query and one Redis ping.
> Dependencies: SQLAlchemy engine, Redis client, FastAPI, and Pydantic.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    """Response confirming that the API process is serving requests."""

    status: Literal["ok"] = Field(description="Process liveness status.")


class ReadinessResponse(BaseModel):
    """Response describing whether required runtime dependencies are available."""

    status: Literal["ready", "not_ready"] = Field(
        description="Whether the application can serve traffic."
    )
    components: dict[str, Literal["ok", "unavailable"]] = Field(
        description="Availability of required backing services."
    )


@router.get("/health/live", response_model=LivenessResponse, summary="Check process liveness")
def live() -> LivenessResponse:
    """Return success while the API process is running."""
    return LivenessResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    summary="Check backing-service readiness",
)
def ready(request: Request, response: Response) -> ReadinessResponse | JSONResponse:
    """Check PostgreSQL and Redis and report unavailable dependencies."""
    components: dict[str, Literal["ok", "unavailable"]] = {}

    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        components["database"] = "ok"
    except SQLAlchemyError:
        logger.exception("Database readiness check failed", extra={"component": "database"})
        components["database"] = "unavailable"

    try:
        request.app.state.redis.ping()
        components["redis"] = "ok"
    except RedisError:
        logger.exception("Redis readiness check failed", extra={"component": "redis"})
        components["redis"] = "unavailable"

    if "unavailable" in components.values():
        response.status_code = 503
        return JSONResponse(
            status_code=503,
            content=ReadinessResponse(status="not_ready", components=components).model_dump(),
        )

    return ReadinessResponse(status="ready", components=components)
