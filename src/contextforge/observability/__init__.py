"""
ContextForge Observability Package

Provides comprehensive observability stack:
- LangFuse tracing for RAG runs
- LangSmith for CI evaluation
- Prometheus metrics (RED + business metrics)
- OpenTelemetry distributed tracing
- Cost tracking with budget alerts
"""

from contextforge.observability.cost import (
    MODEL_PRICING,
    BudgetStatus,
    CostConfig,
    CostTracker,
    TokenUsage,
    calculate_cost,
    configure_cost_tracking,
    extract_tokens_from_response,
    get_cost_tracker,
    track_cost,
)
from contextforge.observability.langfuse import (
    LangFuseConfig,
    LangFuseTracer,
    TraceContext,
    configure_langfuse,
    get_tracer,
    trace_rag_run,
)
from contextforge.observability.langsmith import (
    ExperimentConfig,
    LangSmithConfig,
    LangSmithEvaluator,
    create_langsmith_evaluator,
    get_default_evaluators,
)
from contextforge.observability.metrics import (
    Timer,
    get_content_type,
    get_metrics_output,
    get_registry,
    record_cache,
    record_chunks_created,
    record_cost,
    record_db_connections,
    record_db_query,
    record_documents_processed,
    record_embeddings_created,
    record_evaluation_run,
    record_http_request,
    record_ingestion_job,
    record_queue_depth,
    record_rag_error,
    record_rag_request,
    record_rag_stage,
    record_rate_limit,
    record_tokens,
    record_vector_search,
    time_db_query,
    time_http_request,
    time_rag_stage,
    time_vector_search,
)
from contextforge.observability.tracing import (
    TracingConfig,
    create_rag_metrics,
    get_meter,
    init_tracing,
    instrument_app,
    record_rag_metrics,
    trace_chunking,
    trace_embedding,
    trace_generation,
    trace_ingestion,
    trace_rag_query,
    trace_retrieval,
    trace_verification,
)
from contextforge.observability.tracing import (
    get_tracer as get_otel_tracer,
)

__all__ = [
    # LangFuse
    "LangFuseConfig",
    "LangFuseTracer",
    "TraceContext",
    "get_tracer",
    "configure_langfuse",
    "trace_rag_run",
    # LangSmith
    "LangSmithConfig",
    "LangSmithEvaluator",
    "ExperimentConfig",
    "create_langsmith_evaluator",
    "get_default_evaluators",
    # Metrics
    "get_registry",
    "record_http_request",
    "record_rag_request",
    "record_rag_stage",
    "record_rag_error",
    "record_tokens",
    "record_cost",
    "record_cache",
    "record_queue_depth",
    "record_db_connections",
    "record_db_query",
    "record_vector_search",
    "record_ingestion_job",
    "record_documents_processed",
    "record_chunks_created",
    "record_embeddings_created",
    "record_evaluation_run",
    "record_rate_limit",
    "get_metrics_output",
    "get_content_type",
    "time_rag_stage",
    "time_http_request",
    "time_db_query",
    "time_vector_search",
    "Timer",
    # Tracing
    "TracingConfig",
    "init_tracing",
    "instrument_app",
    "get_otel_tracer",
    "get_meter",
    "trace_rag_query",
    "trace_retrieval",
    "trace_generation",
    "trace_verification",
    "trace_embedding",
    "trace_chunking",
    "trace_ingestion",
    "create_rag_metrics",
    "record_rag_metrics",
    # Cost
    "CostConfig",
    "CostTracker",
    "TokenUsage",
    "BudgetStatus",
    "calculate_cost",
    "extract_tokens_from_response",
    "get_cost_tracker",
    "configure_cost_tracking",
    "track_cost",
    "MODEL_PRICING",
]
