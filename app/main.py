"""
> Why: Assemble the FastAPI application and manage shared process resources.
> Throughput: Stateless HTTP serving; readiness checks perform dependency probes.
> Dependencies: FastAPI, PostgreSQL via SQLAlchemy, Redis, and application settings.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.properties import router as properties_router
from app.api.routes.qr import router as qr_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_context

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API application with validated settings and managed resources."""
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)   # 2. Configure logging

    # 4. Enters lifespan()
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        engine = create_engine(app_settings.database_url, pool_pre_ping=True)   # db connection pool setup
        redis_client = Redis.from_url(app_settings.redis_url, decode_responses=True) # redis connect
        application.state.engine = engine   # Attach db to application state for later use
        application.state.session_factory = sessionmaker(engine, expire_on_commit=False)
        application.state.redis = redis_client # Attach redis to application state for later use
        logger.info("Application startup complete") # Listening for incoming HTTP requests.
        try:
            yield
        finally:
            try:
                redis_client.close()
            finally:
                engine.dispose()
            logger.info("Application shutdown complete")

    # 3. Create fastapi instance
    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="HomeTag AI inventory and maintenance platform API.",
        lifespan=lifespan,      # Run lifespan, which points to lifespan function
    )
    application.state.settings = app_settings

    # 4. API route registration
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(properties_router)
    application.include_router(inventory_router)
    application.include_router(qr_router)

    # Register your custom handlers and middleware into internal 
    # lists/dictionaries inside Starlette (FastAPI's underlying engine)
    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail: dict[str, object] = exc.detail if isinstance(exc.detail, dict) else {}
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": detail.get("code", "request_failed"),
                    "message": detail.get("message", "The request could not be completed."),
                    "request_id": request_id,
                }
            },
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed.",
                    "request_id": request_id,
                    "details": errors,
                }
            },
        )

    @application.middleware("http")
    async def correlate_request(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)

    return application

# uvicorn main:app
# Uvicorn imports main.py and calls create_app()
# Run create_app() to initialize the FastAPI application
app = create_app()
