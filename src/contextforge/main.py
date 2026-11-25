"""
ContextForge FastAPI Application

Main entry point with lifespan management, middleware stack, and API routers.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware

from contextforge.config import settings
from contextforge.storage.database import close_db, init_db

# =============================================================================
# Structured Logging Setup
# =============================================================================

def configure_logging() -> None:
    """Configure structured JSON logging with request IDs."""
    log_level = settings.LOG_LEVEL
    log_format = settings.LOG_FORMAT

    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )

    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


configure_logging()
logger = structlog.get_logger(__name__)

# =============================================================================
# Prometheus Metrics (Lazy Initialization to Avoid Duplicate Registration)
# =============================================================================

from prometheus_client import REGISTRY


def _get_or_create_metric(metric_type, name, *args, **kwargs):
    """Get existing metric or create new one to avoid duplicate registration."""
    try:
        return REGISTRY._names_to_collectors[name]
    except KeyError:
        return metric_type(name, *args, **kwargs)


REQUEST_COUNT = _get_or_create_metric(
    Counter,
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = _get_or_create_metric(
    Histogram,
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

INGESTION_JOBS = _get_or_create_metric(
    Counter,
    "ingestion_jobs_total",
    "Total ingestion jobs",
    ["status", "source_type"],
)

CHUNK_COUNT = _get_or_create_metric(
    Histogram,
    "chunk_count",
    "Number of chunks per document",
    ["strategy"],
)

EMBEDDING_LATENCY = _get_or_create_metric(
    Histogram,
    "embedding_duration_seconds",
    "Embedding generation latency in seconds",
    ["provider", "model"],
)

# =============================================================================
# Middleware
# =============================================================================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add request ID to all requests and responses."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        # Add to structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect Prometheus metrics for requests."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        method = request.method
        path = request.url.path

        with REQUEST_LATENCY.labels(method=method, endpoint=path).time():
            response = await call_next(request)

        REQUEST_COUNT.labels(
            method=method,
            endpoint=path,
            status=response.status_code,
        ).inc()

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting using Redis."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)

        # TODO: Implement token bucket rate limiting with Redis
        # This is a placeholder - full implementation in src/contextforge/middleware/rate_limit.py
        return await call_next(request)


# =============================================================================
# Exception Handlers
# =============================================================================

class ContextForgeException(Exception):
    """Base exception for ContextForge."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(ContextForgeException):
    """Validation error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, status_code=422, details=details)


class NotFoundError(ContextForgeException):
    """Resource not found error."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            f"{resource} not found: {identifier}",
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class IngestionError(ContextForgeException):
    """Ingestion pipeline error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, status_code=500, details=details)


async def contextforge_exception_handler(request: Request, exc: ContextForgeException) -> JSONResponse:
    """Handle ContextForge exceptions."""
    logger.error(
        "contextforge_exception",
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Handle validation errors."""
    return await contextforge_exception_handler(request, exc)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.exception(
        "unhandled_exception",
        error=str(exc),
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("application_starting", app_name=settings.APP_NAME, env=settings.APP_ENV)

    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.exception("database_initialization_failed", error=str(e))
        raise

    # TODO: Initialize vector stores, embedding clients, etc.

    yield

    # Shutdown
    logger.info("application_shutting_down")
    await close_db()
    logger.info("database_closed")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title=settings.APP_NAME,
    description="ContextForge - Enterprise RAG Pipeline with Multi-Strategy Chunking & Embedding",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)

# Middleware stack (order matters - last added = outermost)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Exception handlers
app.add_exception_handler(ContextForgeException, contextforge_exception_handler)
app.add_exception_handler(ValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# =============================================================================
# Health & Metrics Endpoints
# =============================================================================

@app.get("/health", tags=["health"])
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "env": settings.APP_ENV,
    }


@app.get("/metrics", tags=["monitoring"])
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# API Routers
# =============================================================================

from contextforge.api.routes import ingestion_router, mcp_router, query_router

app.include_router(ingestion_router, tags=["ingestion"])
app.include_router(query_router, tags=["query"])
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])


# =============================================================================
# Root
# =============================================================================

@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "contextforge.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
        workers=settings.APP_WORKERS if not settings.APP_DEBUG else 1,
    )
