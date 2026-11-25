"""
LangFuse Integration for Tracing

Provides client and decorators for tracing every RAG run:
- Input (query, parameters)
- Retrieval (documents, scores, latency)
- Synthesis (generation, tokens, latency)
- Verification (evaluation scores, citations)
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from typing import Any

from pydantic import BaseModel, Field

# Optional import - LangFuse may not be installed
try:
    from langfuse import Langfuse
    from langfuse.model import CreateEvent, CreateGeneration, CreateSpan, CreateTrace
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None
    CreateTrace = CreateSpan = CreateGeneration = CreateEvent = None


class LangFuseConfig(BaseModel):
    """Configuration for LangFuse client."""

    public_key: str = Field(default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY", ""))
    secret_key: str = Field(default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY", ""))
    host: str = Field(default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    enabled: bool = Field(default=True)
    flush_interval: float = 5.0  # seconds
    debug: bool = False


@dataclass
class TraceContext:
    """Context for a traced RAG run."""

    trace_id: str
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    spans: list[Any] = field(default_factory=list)
    generations: list[Any] = field(default_factory=list)


class LangFuseTracer:
    """
    LangFuse tracer for RAG pipelines.

    Usage:
        tracer = LangFuseTracer(config)
        with tracer.trace("rag_query", user_id="user123") as ctx:
            # Retrieval
            with tracer.span(ctx, "retrieval") as span:
                docs = retrieve(query)
                span.end(output={"num_docs": len(docs)})

            # Generation
            with tracer.generation(ctx, "generation", model="gpt-4") as gen:
                answer = generate(query, docs)
                gen.end(output=answer, usage={"prompt_tokens": 100, "completion_tokens": 200})
    """

    def __init__(self, config: LangFuseConfig = None):
        self.config = config or LangFuseConfig()
        self._client: Langfuse | None = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize LangFuse client."""
        if not LANGFUSE_AVAILABLE:
            if self.config.debug:
                print("[LangFuse] Not available - install langfuse package")
            return

        if not self.config.public_key or not self.config.secret_key:
            if self.config.debug:
                print("[LangFuse] Credentials not configured")
            return

        if not self.config.enabled:
            return

        try:
            self._client = Langfuse(
                public_key=self.config.public_key,
                secret_key=self.config.secret_key,
                host=self.config.host,
                flush_interval=self.config.flush_interval,
                debug=self.config.debug,
            )
        except Exception as e:
            if self.config.debug:
                print(f"[LangFuse] Failed to initialize: {e}")

    @property
    def is_enabled(self) -> bool:
        """Check if tracer is enabled and configured."""
        return self._client is not None

    def create_trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] = None,
        input_data: dict[str, Any] = None,
    ) -> TraceContext:
        """Create a new trace."""
        trace_id = str(uuid.uuid4())
        ctx = TraceContext(
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )

        if self._client:
            try:
                self._client.trace(
                    CreateTrace(
                        id=trace_id,
                        name=name,
                        user_id=user_id,
                        session_id=session_id,
                        metadata=metadata or {},
                        input=input_data,
                        timestamp=datetime.utcnow(),
                    )
                )
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to create trace: {e}")

        return ctx

    @contextmanager
    def trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] = None,
        input_data: dict[str, Any] = None,
    ):
        """Context manager for tracing a complete RAG run."""
        ctx = self.create_trace(name, user_id, session_id, metadata, input_data)
        try:
            yield ctx
        finally:
            self.end_trace(ctx)

    def end_trace(self, ctx: TraceContext, output: dict[str, Any] = None) -> None:
        """End a trace."""
        if self._client:
            try:
                self._client.trace(
                    CreateTrace(
                        id=ctx.trace_id,
                        output=output,
                        timestamp=datetime.utcnow(),
                    )
                )
                self._client.flush()
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to end trace: {e}")

    @contextmanager
    def span(
        self,
        ctx: TraceContext,
        name: str,
        metadata: dict[str, Any] = None,
    ):
        """Context manager for a span within a trace."""
        span_id = str(uuid.uuid4())
        start_time = time.time()

        span_obj = None
        if self._client:
            try:
                span_obj = self._client.span(
                    CreateSpan(
                        id=span_id,
                        trace_id=ctx.trace_id,
                        name=name,
                        metadata=metadata or {},
                        start_time=datetime.utcfromtimestamp(start_time),
                    )
                )
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to create span: {e}")

        try:
            yield span_obj
        finally:
            end_time = time.time()
            if self._client and span_obj:
                try:
                    span_obj.end(
                        end_time=datetime.utcfromtimestamp(end_time),
                    )
                except Exception as e:
                    if self.config.debug:
                        print(f"[LangFuse] Failed to end span: {e}")

    @contextmanager
    def generation(
        self,
        ctx: TraceContext,
        name: str,
        model: str,
        metadata: dict[str, Any] = None,
        input_data: dict[str, Any] = None,
    ):
        """Context manager for an LLM generation."""
        generation_id = str(uuid.uuid4())
        start_time = time.time()

        gen_obj = None
        if self._client:
            try:
                gen_obj = self._client.generation(
                    CreateGeneration(
                        id=generation_id,
                        trace_id=ctx.trace_id,
                        name=name,
                        model=model,
                        metadata=metadata or {},
                        input=input_data,
                        start_time=datetime.utcfromtimestamp(start_time),
                    )
                )
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to create generation: {e}")

        try:
            yield gen_obj
        finally:
            end_time = time.time()
            if self._client and gen_obj:
                try:
                    gen_obj.end(
                        end_time=datetime.utcfromtimestamp(end_time),
                    )
                except Exception as e:
                    if self.config.debug:
                        print(f"[LangFuse] Failed to end generation: {e}")

    def event(
        self,
        ctx: TraceContext,
        name: str,
        metadata: dict[str, Any] = None,
        input_data: dict[str, Any] = None,
        output_data: dict[str, Any] = None,
    ) -> None:
        """Log an event within a trace."""
        if self._client:
            try:
                self._client.event(
                    CreateEvent(
                        id=str(uuid.uuid4()),
                        trace_id=ctx.trace_id,
                        name=name,
                        metadata=metadata or {},
                        input=input_data,
                        output=output_data,
                        timestamp=datetime.utcnow(),
                    )
                )
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to log event: {e}")

    def score(
        self,
        ctx: TraceContext,
        name: str,
        value: float,
        comment: str = "",
        metadata: dict[str, Any] = None,
    ) -> None:
        """Log a score/evaluation metric."""
        if self._client:
            try:
                self._client.score(
                    trace_id=ctx.trace_id,
                    name=name,
                    value=value,
                    comment=comment,
                    metadata=metadata or {},
                )
            except Exception as e:
                if self.config.debug:
                    print(f"[LangFuse] Failed to log score: {e}")

    def flush(self) -> None:
        """Flush pending events."""
        if self._client:
            self._client.flush()


# Decorators for easy tracing

def trace_rag_run(
    tracer: LangFuseTracer,
    name: str = "rag_query",
    user_id_param: str = "user_id",
    session_id_param: str = "session_id",
):
    """
    Decorator to trace a RAG run function.

    Args:
        tracer: LangFuseTracer instance
        name: Trace name
        user_id_param: Parameter name for user_id
        session_id_param: Parameter name for session_id
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract user/session from kwargs
            user_id = kwargs.get(user_id_param)
            session_id = kwargs.get(session_id_param)

            # Extract input for tracing
            input_data = {"args": str(args)[:500], "kwargs": {k: str(v)[:500] for k, v in kwargs.items()}}

            with tracer.trace(name, user_id, session_id, input_data=input_data) as ctx:
                try:
                    result = func(*args, **kwargs)
                    tracer.end_trace(ctx, output={"success": True})
                    return result
                except Exception as e:
                    tracer.end_trace(ctx, output={"success": False, "error": str(e)})
                    raise

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            user_id = kwargs.get(user_id_param)
            session_id = kwargs.get(session_id_param)

            input_data = {"args": str(args)[:500], "kwargs": {k: str(v)[:500] for k, v in kwargs.items()}}

            with tracer.trace(name, user_id, session_id, input_data=input_data) as ctx:
                try:
                    result = await func(*args, **kwargs)
                    tracer.end_trace(ctx, output={"success": True})
                    return result
                except Exception as e:
                    tracer.end_trace(ctx, output={"success": False, "error": str(e)})
                    raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def trace_retrieval(tracer: LangFuseTracer):
    """Decorator to trace retrieval step."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Assume first arg is trace context or we get it from somewhere
            ctx = kwargs.get("_trace_ctx")
            if ctx and tracer.is_enabled:
                with tracer.span(ctx, "retrieval") as span:
                    result = func(*args, **kwargs)
                    if span:
                        span.end(output={"num_results": len(result) if isinstance(result, list) else 1})
                    return result
            return func(*args, **kwargs)
        return wrapper
    return decorator


def trace_generation(tracer: LangFuseTracer, model: str):
    """Decorator to trace generation step."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            ctx = kwargs.get("_trace_ctx")
            if ctx and tracer.is_enabled:
                with tracer.generation(ctx, "generation", model=model) as gen:
                    result = func(*args, **kwargs)
                    if gen:
                        # Try to extract usage from result
                        usage = getattr(result, "usage", None) or {}
                        gen.end(output=result, usage=usage)
                    return result
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Global tracer instance (lazy initialization)
_global_tracer: LangFuseTracer | None = None


def get_tracer(config: LangFuseConfig = None) -> LangFuseTracer:
    """Get or create global tracer instance."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = LangFuseTracer(config)
    return _global_tracer


def configure_langfuse(
    public_key: str = None,
    secret_key: str = None,
    host: str = None,
    enabled: bool = True,
) -> LangFuseTracer:
    """Configure and return global LangFuse tracer."""
    global _global_tracer
    config = LangFuseConfig(
        public_key=public_key or os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=secret_key or os.getenv("LANGFUSE_SECRET_KEY", ""),
        host=host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        enabled=enabled,
    )
    _global_tracer = LangFuseTracer(config)
    return _global_tracer
