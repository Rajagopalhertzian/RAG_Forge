"""
Prometheus Metrics for ContextForge

Defines RED metrics (Rate, Errors, Duration) + business metrics:
- RPS (requests per second)
- Latency percentiles (p50, p95, p99)
- Queue depth
- Database connections
- Token usage
- Cost tracking
- Cache hit rates
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CollectorRegistry

# Global registry
_registry: CollectorRegistry | None = None


def get_registry() -> CollectorRegistry:
    """Get or create global Prometheus registry."""
    global _registry
    if _registry is None:
        _registry = CollectorRegistry()
    return _registry


# =============================================================================
# RED Metrics (Rate, Errors, Duration)
# =============================================================================

# HTTP Requests
http_requests_total = Counter(
    "contextforge_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=get_registry(),
)

http_request_duration_seconds = Histogram(
    "contextforge_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=get_registry(),
)

http_requests_in_progress = Gauge(
    "contextforge_http_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "endpoint"],
    registry=get_registry(),
)

# RAG Pipeline Requests
rag_requests_total = Counter(
    "contextforge_rag_requests_total",
    "Total RAG pipeline requests",
    ["status"],  # success, error, timeout
    registry=get_registry(),
)

rag_request_duration_seconds = Histogram(
    "contextforge_rag_request_duration_seconds",
    "RAG pipeline request latency in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=get_registry(),
)

rag_retrieval_duration_seconds = Histogram(
    "contextforge_rag_retrieval_duration_seconds",
    "Retrieval step latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    registry=get_registry(),
)

rag_generation_duration_seconds = Histogram(
    "contextforge_rag_generation_duration_seconds",
    "Generation step latency in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=get_registry(),
)

rag_verification_duration_seconds = Histogram(
    "contextforge_rag_verification_duration_seconds",
    "Verification step latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=get_registry(),
)

# Errors
rag_errors_total = Counter(
    "contextforge_rag_errors_total",
    "Total RAG pipeline errors",
    ["stage", "error_type"],  # stage: retrieval, generation, verification
    registry=get_registry(),
)


# =============================================================================
# Business Metrics
# =============================================================================

# Token Usage
tokens_total = Counter(
    "contextforge_tokens_total",
    "Total tokens consumed",
    ["model", "type"],  # type: prompt, completion, total
    registry=get_registry(),
)

prompt_tokens_total = Counter(
    "contextforge_prompt_tokens_total",
    "Total prompt tokens",
    ["model"],
    registry=get_registry(),
)

completion_tokens_total = Counter(
    "contextforge_completion_tokens_total",
    "Total completion tokens",
    ["model"],
    registry=get_registry(),
)

# Cost Tracking (USD)
cost_usd_total = Counter(
    "contextforge_cost_usd_total",
    "Total cost in USD",
    ["model", "operation"],  # operation: embedding, generation, rerank
    registry=get_registry(),
)

daily_cost_usd = Gauge(
    "contextforge_daily_cost_usd",
    "Daily cost in USD",
    ["date"],
    registry=get_registry(),
)

# Cache Metrics
cache_hits_total = Counter(
    "contextforge_cache_hits_total",
    "Total cache hits",
    ["cache_type"],  # embedding, retrieval, generation
    registry=get_registry(),
)

cache_misses_total = Counter(
    "contextforge_cache_misses_total",
    "Total cache misses",
    ["cache_type"],
    registry=get_registry(),
)

cache_hit_rate = Gauge(
    "contextforge_cache_hit_rate",
    "Cache hit rate (0-1)",
    ["cache_type"],
    registry=get_registry(),
)

# Queue Depth (Celery)
queue_depth = Gauge(
    "contextforge_queue_depth",
    "Task queue depth",
    ["queue_name"],
    registry=get_registry(),
)

# Database Connections
db_connections_active = Gauge(
    "contextforge_db_connections_active",
    "Active database connections",
    registry=get_registry(),
)

db_connections_idle = Gauge(
    "contextforge_db_connections_idle",
    "Idle database connections",
    registry=get_registry(),
)

db_query_duration_seconds = Histogram(
    "contextforge_db_query_duration_seconds",
    "Database query latency in seconds",
    ["operation"],  # select, insert, update, delete
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=get_registry(),
)

# Vector Store Metrics
vector_search_duration_seconds = Histogram(
    "contextforge_vector_search_duration_seconds",
    "Vector search latency in seconds",
    ["store_type"],  # pgvector, faiss, weaviate
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
    registry=get_registry(),
)

vector_index_size = Gauge(
    "contextforge_vector_index_size",
    "Vector index size (number of vectors)",
    ["store_type"],
    registry=get_registry(),
)

# Ingestion Metrics
ingestion_jobs_total = Counter(
    "contextforge_ingestion_jobs_total",
    "Total ingestion jobs",
    ["status", "source_type"],  # status: started, completed, failed
    registry=get_registry(),
)

ingestion_duration_seconds = Histogram(
    "contextforge_ingestion_duration_seconds",
    "Ingestion job duration in seconds",
    ["source_type"],
    buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600],
    registry=get_registry(),
)

documents_processed_total = Counter(
    "contextforge_documents_processed_total",
    "Total documents processed",
    ["source_type", "status"],
    registry=get_registry(),
)

chunks_created_total = Counter(
    "contextforge_chunks_created_total",
    "Total chunks created",
    ["strategy"],
    registry=get_registry(),
)

embeddings_created_total = Counter(
    "contextforge_embeddings_created_total",
    "Total embeddings created",
    ["model"],
    registry=get_registry(),
)

# Evaluation Metrics
evaluation_runs_total = Counter(
    "contextforge_evaluation_runs_total",
    "Total evaluation runs",
    ["type", "status"],  # type: retrieval, generation, chunking, embedding
    registry=get_registry(),
)

evaluation_score = Gauge(
    "contextforge_evaluation_score",
    "Evaluation metric score",
    ["type", "metric"],  # metric: mrr_at_10, faithfulness, etc.
    registry=get_registry(),
)

# Rate Limiting
rate_limit_requests_total = Counter(
    "contextforge_rate_limit_requests_total",
    "Total rate-limited requests",
    ["action"],  # allowed, rejected
    registry=get_registry(),
)


# =============================================================================
# MCP Gateway Metrics
# =============================================================================

# Tool call metrics
mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool", "status"],  # status: success, error, rate_limited
    registry=get_registry(),
)

mcp_tool_latency_seconds = Histogram(
    "mcp_tool_latency_seconds",
    "MCP tool call latency in seconds",
    ["tool"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=get_registry(),
)

# Active sessions
mcp_active_sessions = Gauge(
    "mcp_active_sessions",
    "Number of active MCP sessions",
    registry=get_registry(),
)

# Rate limit exceeded
mcp_rate_limit_exceeded_total = Counter(
    "mcp_rate_limit_exceeded_total",
    "Total MCP rate limit exceeded events",
    ["client_id"],
    registry=get_registry(),
)


# =============================================================================
# Helper Functions
# =============================================================================

@dataclass
class MetricsSnapshot:
    """Snapshot of current metrics for reporting."""

    timestamp: float = field(default_factory=time.time)
    http_rps: float = 0.0
    http_p50: float = 0.0
    http_p95: float = 0.0
    http_p99: float = 0.0
    rag_rps: float = 0.0
    rag_p50: float = 0.0
    rag_p95: float = 0.0
    rag_p99: float = 0.0
    error_rate: float = 0.0
    cache_hit_rate: float = 0.0
    daily_cost_usd: float = 0.0
    queue_depth: int = 0
    db_connections: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "http_rps": self.http_rps,
            "http_p50": self.http_p50,
            "http_p95": self.http_p95,
            "http_p99": self.http_p99,
            "rag_rps": self.rag_rps,
            "rag_p50": self.rag_p50,
            "rag_p95": self.rag_p95,
            "rag_p99": self.rag_p99,
            "error_rate": self.error_rate,
            "cache_hit_rate": self.cache_hit_rate,
            "daily_cost_usd": self.daily_cost_usd,
            "queue_depth": self.queue_depth,
            "db_connections": self.db_connections,
        }


def record_http_request(method: str, endpoint: str, status: int, duration: float) -> None:
    """Record HTTP request metrics."""
    http_requests_total.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_rag_request(status: str, duration: float) -> None:
    """Record RAG pipeline request metrics."""
    rag_requests_total.labels(status=status).inc()
    rag_request_duration_seconds.observe(duration)


def record_rag_stage(stage: str, duration: float) -> None:
    """Record RAG stage latency."""
    if stage == "retrieval":
        rag_retrieval_duration_seconds.observe(duration)
    elif stage == "generation":
        rag_generation_duration_seconds.observe(duration)
    elif stage == "verification":
        rag_verification_duration_seconds.observe(duration)


def record_rag_error(stage: str, error_type: str) -> None:
    """Record RAG error."""
    rag_errors_total.labels(stage=stage, error_type=error_type).inc()


def record_tokens(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record token usage."""
    tokens_total.labels(model=model, type="prompt").inc(prompt_tokens)
    tokens_total.labels(model=model, type="completion").inc(completion_tokens)
    tokens_total.labels(model=model, type="total").inc(prompt_tokens + completion_tokens)
    prompt_tokens_total.labels(model=model).inc(prompt_tokens)
    completion_tokens_total.labels(model=model).inc(completion_tokens)


def record_cost(model: str, operation: str, cost_usd: float) -> None:
    """Record cost in USD."""
    cost_usd_total.labels(model=model, operation=operation).inc(cost_usd)


def record_cache(cache_type: str, hit: bool) -> None:
    """Record cache hit/miss."""
    if hit:
        cache_hits_total.labels(cache_type=cache_type).inc()
    else:
        cache_misses_total.labels(cache_type=cache_type).inc()

    # Update hit rate gauge
    hits = cache_hits_total.labels(cache_type=cache_type)._value._value
    misses = cache_misses_total.labels(cache_type=cache_type)._value._value
    total = hits + misses
    if total > 0:
        cache_hit_rate.labels(cache_type=cache_type).set(hits / total)


def record_queue_depth(queue_name: str, depth: int) -> None:
    """Record queue depth."""
    queue_depth.labels(queue_name=queue_name).set(depth)


def record_db_connections(active: int, idle: int) -> None:
    """Record database connection pool stats."""
    db_connections_active.set(active)
    db_connections_idle.set(idle)


def record_db_query(operation: str, duration: float) -> None:
    """Record database query latency."""
    db_query_duration_seconds.labels(operation=operation).observe(duration)


def record_vector_search(store_type: str, duration: float) -> None:
    """Record vector search latency."""
    vector_search_duration_seconds.labels(store_type=store_type).observe(duration)


def record_ingestion_job(status: str, source_type: str, duration: float = None) -> None:
    """Record ingestion job."""
    ingestion_jobs_total.labels(status=status, source_type=source_type).inc()
    if duration is not None:
        ingestion_duration_seconds.labels(source_type=source_type).observe(duration)


def record_documents_processed(source_type: str, status: str, count: int = 1) -> None:
    """Record documents processed."""
    documents_processed_total.labels(source_type=source_type, status=status).inc(count)


def record_chunks_created(strategy: str, count: int) -> None:
    """Record chunks created."""
    chunks_created_total.labels(strategy=strategy).inc(count)


def record_embeddings_created(model: str, count: int) -> None:
    """Record embeddings created."""
    embeddings_created_total.labels(model=model).inc(count)


def record_evaluation_run(eval_type: str, status: str, scores: dict[str, float] = None) -> None:
    """Record evaluation run."""
    evaluation_runs_total.labels(type=eval_type, status=status).inc()
    if scores:
        for metric, score in scores.items():
            evaluation_score.labels(type=eval_type, metric=metric).set(score)


def record_rate_limit(action: str) -> None:
    """Record rate limit action."""
    rate_limit_requests_total.labels(action=action).inc()


def get_metrics_output() -> bytes:
    """Get Prometheus metrics output."""
    return generate_latest(get_registry())


def get_content_type() -> str:
    """Get Prometheus content type."""
    return CONTENT_TYPE_LATEST


# =============================================================================
# Context Managers for Timing
# =============================================================================

class Timer:
    """Context manager for timing operations."""

    def __init__(self, histogram: Histogram, labels: dict[str, str] = None):
        self.histogram = histogram
        self.labels = labels or {}
        self.start_time = 0.0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if self.labels:
            self.histogram.labels(**self.labels).observe(duration)
        else:
            self.histogram.observe(duration)
        return False


def time_rag_stage(stage: str) -> Timer:
    """Create timer for RAG stage."""
    histograms = {
        "retrieval": rag_retrieval_duration_seconds,
        "generation": rag_generation_duration_seconds,
        "verification": rag_verification_duration_seconds,
    }
    return Timer(histograms.get(stage, rag_request_duration_seconds))


def time_http_request(method: str, endpoint: str) -> Timer:
    """Create timer for HTTP request."""
    return Timer(http_request_duration_seconds, {"method": method, "endpoint": endpoint})


def time_db_query(operation: str) -> Timer:
    """Create timer for database query."""
    return Timer(db_query_duration_seconds, {"operation": operation})


def time_vector_search(store_type: str) -> Timer:
    """Create timer for vector search."""
    return Timer(vector_search_duration_seconds, {"store_type": store_type})
