"""
Cost Tracking Middleware for FastAPI

Provides per-request token extraction, cost calculation, and database logging.
Integrates with the cost tracking system for budget enforcement.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from contextforge.observability.cost import (
    CostTracker,
    TokenUsage,
    calculate_cost,
    extract_tokens_from_response,
    get_cost_tracker,
)
from contextforge.observability.metrics import record_cost, record_tokens


@dataclass
class CostTrackingConfig:
    """Configuration for cost tracking middleware."""

    # Enable/disable middleware
    enabled: bool = True

    # Track all requests or only specific paths
    tracked_paths: list[str] = field(default_factory=lambda: ["/api/v1/rag", "/api/v1/chat"])

    # Exclude paths from tracking
    excluded_paths: list[str] = field(default_factory=lambda: ["/health", "/metrics", "/docs", "/openapi.json"])

    # Extract user ID from request
    user_id_header: str = "x-user-id"
    user_id_query_param: str = "user_id"

    # Custom cost tracker
    cost_tracker: CostTracker | None = None


class CostTrackingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for tracking LLM costs per request.

    Tracks:
    - Token usage from response headers (if LLM provider returns them)
    - Calculates USD cost
    - Logs to cost tracker for budget enforcement
    - Records Prometheus metrics

    Usage:
        app.add_middleware(CostTrackingMiddleware, config=CostTrackingConfig(...))
    """

    def __init__(
        self,
        app: ASGIApp,
        config: CostTrackingConfig = None,
    ):
        super().__init__(app)
        self.config = config or CostTrackingConfig()
        self.tracker = self.config.cost_tracker or get_cost_tracker()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if path should be tracked
        if not self._should_track(request):
            return await call_next(request)

        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract user ID
        user_id = self._extract_user_id(request)
        request.state.user_id = user_id

        # Check budget before processing
        if self.config.enabled:
            allowed, reason = self.tracker.can_proceed(user_id)
            if not allowed:
                return Response(
                    content=f"Budget exceeded: {reason}",
                    status_code=429,
                    headers={"X-Budget-Reason": reason},
                )

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        # Track cost from response (if available)
        if self.config.enabled:
            await self._track_response_cost(request, response, user_id, request_id, duration)

        return response

    def _should_track(self, request: Request) -> bool:
        """Check if request path should be tracked."""
        path = request.url.path

        # Check excluded paths
        for excluded in self.config.excluded_paths:
            if path.startswith(excluded):
                return False

        # Check tracked paths (if specified)
        if self.config.tracked_paths:
            for tracked in self.config.tracked_paths:
                if path.startswith(tracked):
                    return True
            return False

        return True

    def _extract_user_id(self, request: Request) -> str | None:
        """Extract user ID from request."""
        # From header
        user_id = request.headers.get(self.config.user_id_header)
        if user_id:
            return user_id

        # From query param
        user_id = request.query_params.get(self.config.user_id_query_param)
        if user_id:
            return user_id

        # From state (set by auth middleware)
        return getattr(request.state, "user_id", None)

    async def _track_response_cost(
        self,
        request: Request,
        response: Response,
        user_id: str | None,
        request_id: str,
        duration: float,
    ) -> None:
        """Extract and track cost from response."""
        # Try to get token usage from response headers
        # Some LLM providers return usage in headers
        usage = self._extract_usage_from_headers(response.headers)

        # If not in headers, try to parse response body (for streaming responses)
        if not usage and hasattr(response, "body"):
            # For non-streaming responses, we'd need to capture body
            # This is complex with Starlette - typically done via custom Response class
            pass

        if usage:
            # Record to cost tracker
            self.tracker.record_usage(usage)

            # Record Prometheus metrics
            record_tokens(
                model=usage.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
            record_cost(
                model=usage.model,
                operation=usage.operation,
                cost_usd=usage.cost_usd,
            )

    def _extract_usage_from_headers(self, headers: dict[str, str]) -> TokenUsage | None:
        """Extract token usage from response headers."""
        # Check for common header formats
        # OpenAI: x-ratelimit-limit-tokens, etc. (not usage)
        # Some proxies add usage headers

        # Custom header format: x-llm-usage: prompt=100,completion=50,model=gpt-4o
        usage_header = headers.get("x-llm-usage")
        if usage_header:
            return self._parse_usage_header(usage_header)

        # Check for individual headers
        prompt_tokens = headers.get("x-llm-prompt-tokens")
        completion_tokens = headers.get("x-llm-completion-tokens")
        model = headers.get("x-llm-model")

        if prompt_tokens and completion_tokens:
            return TokenUsage(
                model=model or "unknown",
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(prompt_tokens) + int(completion_tokens),
                operation="generation",
            )

        return None

    def _parse_usage_header(self, header: str) -> TokenUsage | None:
        """Parse usage header string."""
        try:
            parts = header.split(",")
            data = {}
            for part in parts:
                if "=" in part:
                    key, value = part.split("=", 1)
                    data[key.strip()] = value.strip()

            return TokenUsage(
                model=data.get("model", "unknown"),
                prompt_tokens=int(data.get("prompt", 0)),
                completion_tokens=int(data.get("completion", 0)),
                total_tokens=int(data.get("prompt", 0)) + int(data.get("completion", 0)),
                operation=data.get("operation", "generation"),
            )
        except Exception:
            return None


# Alternative: Response wrapper for capturing streaming responses

class CostTrackingResponse(Response):
    """
    Response wrapper that captures body for cost tracking.

    Usage:
        return CostTrackingResponse(content=body, media_type="application/json")
    """

    def __init__(self, *args, cost_tracker: CostTracker = None, **kwargs):
        self._cost_tracker = cost_tracker or get_cost_tracker()
        self._captured_body = b""
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        # Capture body chunks
        async def send_wrapper(message):
            if message["type"] == "http.response.body":
                self._captured_body += message.get("body", b"")
            await send(message)

        await super().__call__(scope, receive, send_wrapper)

        # Process captured body after response
        if self._captured_body:
            self._process_body()

    def _process_body(self) -> None:
        """Process captured response body for token usage."""
        import json

        try:
            body = json.loads(self._captured_body.decode())
            usage = extract_tokens_from_response(body)
            if usage:
                self._cost_tracker.record_usage(usage)
        except Exception:
            pass  # Not JSON or no usage info


# Dependency for getting cost tracker in route handlers

def get_cost_tracker_dependency() -> CostTracker:
    """FastAPI dependency for cost tracker."""
    return get_cost_tracker()


# Route handler decorator for explicit cost tracking

def track_llm_cost(
    operation: str = "generation",
    model_param: str = "model",
    cost_tracker: CostTracker = None,
):
    """
    Decorator for route handlers that call LLMs.

    Usage:
        @app.post("/chat")
        @track_llm_cost(operation="generation")
        async def chat(request: ChatRequest, cost_tracker: CostTracker = Depends(get_cost_tracker_dependency)):
            response = await llm_client.chat(...)
            return response
    """
    def decorator(func: Callable) -> Callable:
        from functools import wraps

        @wraps(func)
        async def wrapper(*args, **kwargs):
            _tracker = cost_tracker or get_cost_tracker()

            # Execute handler
            result = await func(*args, **kwargs)

            # Extract model from kwargs or result
            model = kwargs.get(model_param)
            if not model and hasattr(result, "model"):
                model = result.model

            # Extract token usage
            usage = extract_tokens_from_response(result, model)
            if usage:
                usage.operation = operation
                _tracker.record_usage(usage)

            return result

        return wrapper

    return decorator


# Context manager for manual cost tracking in services

class CostContext:
    """
    Context manager for manual cost tracking in service layers.

    Usage:
        async with CostContext(model="gpt-4o", operation="generation") as ctx:
            response = await llm.generate(prompt)
            ctx.set_usage(response)
    """

    def __init__(
        self,
        model: str,
        operation: str = "generation",
        user_id: str = None,
        request_id: str = None,
        cost_tracker: CostTracker = None,
        metadata: dict[str, Any] = None,
    ):
        self.model = model
        self.operation = operation
        self.user_id = user_id
        self.request_id = request_id or str(uuid.uuid4())
        self.tracker = cost_tracker or get_cost_tracker()
        self.metadata = metadata or {}
        self._usage: TokenUsage | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._usage:
            self.tracker.record_usage(self._usage)
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._usage:
            self.tracker.record_usage(self._usage)
        return False

    def set_usage(self, response: Any) -> None:
        """Set usage from LLM response."""
        self._usage = extract_tokens_from_response(response, self.model)
        if self._usage:
            self._usage.operation = self.operation
            self._usage.user_id = self.user_id
            self._usage.request_id = self.request_id
            self._usage.metadata = self.metadata

    def set_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Manually set token counts."""
        self._usage = TokenUsage(
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            operation=self.operation,
            user_id=self.user_id,
            request_id=self.request_id,
            metadata=self.metadata,
        )


# Utility functions for common patterns

async def track_embedding_cost(
    texts: list[str],
    model: str,
    embedding_fn: Callable,
    cost_tracker: CostTracker = None,
    user_id: str = None,
) -> list[list[float]]:
    """
    Track cost for embedding generation.

    Args:
        texts: Texts to embed
        model: Embedding model name
        embedding_fn: Function that takes texts and returns embeddings
        cost_tracker: Cost tracker instance
        user_id: User ID for budget tracking

    Returns:
        List of embeddings
    """
    _tracker = cost_tracker or get_cost_tracker()

    # Estimate tokens (rough: 1 token ≈ 4 chars)
    total_chars = sum(len(t) for t in texts)
    estimated_tokens = total_chars // 4

    # Check budget
    estimated_cost = calculate_cost(model, estimated_tokens, 0, "embedding")
    allowed, reason = _tracker.can_proceed(user_id, estimated_cost)
    if not allowed:
        raise RuntimeError(f"Budget check failed: {reason}")

    # Generate embeddings
    embeddings = await embedding_fn(texts)

    # Record actual usage (embedding APIs typically return usage)
    # For local models, estimate
    actual_tokens = estimated_tokens
    usage = TokenUsage(
        model=model,
        prompt_tokens=actual_tokens,
        completion_tokens=0,
        total_tokens=actual_tokens,
        operation="embedding",
        user_id=user_id,
    )
    _tracker.record_usage(usage)

    return embeddings


async def track_generation_cost(
    prompt: str,
    model: str,
    generation_fn: Callable,
    cost_tracker: CostTracker = None,
    user_id: str = None,
    **generation_kwargs,
) -> Any:
    """
    Track cost for text generation.

    Args:
        prompt: Input prompt
        model: Generation model name
        generation_fn: Function that generates text
        cost_tracker: Cost tracker instance
        user_id: User ID for budget tracking
        **generation_kwargs: Additional arguments for generation function

    Returns:
        Generation result
    """
    _tracker = cost_tracker or get_cost_tracker()

    # Estimate prompt tokens
    prompt_tokens = len(prompt) // 4
    estimated_cost = calculate_cost(model, prompt_tokens, 0, "generation")

    allowed, reason = _tracker.can_proceed(user_id, estimated_cost)
    if not allowed:
        raise RuntimeError(f"Budget check failed: {reason}")

    # Generate
    result = await generation_fn(prompt, **generation_kwargs)

    # Extract usage
    usage = extract_tokens_from_response(result, model)
    if usage:
        usage.operation = "generation"
        usage.user_id = user_id
    else:
        # Estimate
        completion_text = str(result) if not hasattr(result, "choices") else result.choices[0].message.content
        completion_tokens = len(completion_text) // 4
        usage = TokenUsage(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            operation="generation",
            user_id=user_id,
        )

    _tracker.record_usage(usage)
    return result
