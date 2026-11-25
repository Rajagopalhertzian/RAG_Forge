"""
OpenTelemetry Setup for ContextForge

Configures distributed tracing with:
- Traces → LangFuse (via OTLP)
- Metrics → Prometheus (via OTLP)
- Automatic instrumentation for FastAPI, SQLAlchemy, Redis, HTTPX
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CollectorRegistry


class TracingConfig:
    """Configuration for OpenTelemetry tracing."""

    def __init__(
        self,
        service_name: str = "contextforge",
        service_version: str = "0.1.0",
        otlp_endpoint: str = None,
        enable_console_exporter: bool = False,
        enable_prometheus_metrics: bool = True,
        prometheus_registry: CollectorRegistry = None,
        sample_rate: float = 1.0,
    ):
        self.service_name = service_name
        self.service_version = service_version
        self.otlp_endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        self.enable_console_exporter = enable_console_exporter
        self.enable_prometheus_metrics = enable_prometheus_metrics
        self.prometheus_registry = prometheus_registry
        self.sample_rate = sample_rate


def init_tracing(config: TracingConfig = None) -> tuple[TracerProvider, MeterProvider]:
    """
    Initialize OpenTelemetry tracing and metrics.

    Args:
        config: Tracing configuration

    Returns:
        Tuple of (TracerProvider, MeterProvider)
    """
    if config is None:
        config = TracingConfig()

    # Create resource
    resource = Resource.create({
        SERVICE_NAME: config.service_name,
        SERVICE_VERSION: config.service_version,
        "deployment.environment": os.getenv("APP_ENV", "development"),
    })

    # Initialize trace provider
    trace_provider = TracerProvider(resource=resource)

    # Add OTLP span exporter
    otlp_exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, insecure=True)
    trace_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Add console exporter for debugging
    if config.enable_console_exporter:
        trace_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Set global trace provider
    trace.set_tracer_provider(trace_provider)

    # Initialize meter provider
    readers = []

    # Prometheus metric reader
    if config.enable_prometheus_metrics:
        prometheus_reader = PrometheusMetricReader(registry=config.prometheus_registry)
        readers.append(prometheus_reader)

    # OTLP metric exporter
    otlp_metric_exporter = OTLPMetricExporter(endpoint=config.otlp_endpoint, insecure=True)
    otlp_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=30000)
    readers.append(otlp_reader)

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)

    return trace_provider, meter_provider


def instrument_app(app, config: TracingConfig = None) -> None:
    """
    Instrument FastAPI app with OpenTelemetry.

    Args:
        app: FastAPI application
        config: Tracing configuration
    """
    if config is None:
        config = TracingConfig()

    # Initialize tracing first
    init_tracing(config)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )

    # Instrument SQLAlchemy
    SQLAlchemyInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )

    # Instrument Redis
    RedisInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )

    # Instrument HTTPX
    HTTPXClientInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )

    # Instrument Requests
    RequestsInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )


def get_tracer(name: str = "contextforge") -> trace.Tracer:
    """Get a tracer instance."""
    return trace.get_tracer_provider().get_tracer(name)


def get_meter(name: str = "contextforge") -> metrics.Meter:
    """Get a meter instance."""
    return metrics.get_meter_provider().get_meter(name)


# Custom span helpers for RAG pipeline

@contextmanager
def trace_rag_query(
    query: str,
    user_id: str = None,
    session_id: str = None,
    metadata: dict[str, Any] = None,
):
    """
    Context manager for tracing a complete RAG query.

    Usage:
        with trace_rag_query("What is RAG?", user_id="123") as span:
            # Retrieval
            with trace_retrieval(span, "vector_search") as retr_span:
                docs = retrieve(query)

            # Generation
            with trace_generation(span, "gpt-4") as gen_span:
                answer = generate(query, docs)

            span.set_attribute("rag.answer", answer)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.query",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.query": query,
            "rag.user_id": user_id or "",
            "rag.session_id": session_id or "",
            **(metadata or {}),
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_retrieval(
    parent_span: trace.Span,
    store_type: str,
    query: str = None,
    top_k: int = None,
    filters: dict[str, Any] = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing retrieval step.

    Usage:
        with trace_retrieval(span, "pgvector", query="test", top_k=10) as retr_span:
            docs = vector_search(query, top_k)
            retr_span.set_attribute("rag.retrieval.num_results", len(docs))
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.retrieval",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.retrieval.store_type": store_type,
            "rag.retrieval.query": query or "",
            "rag.retrieval.top_k": top_k or 0,
            "rag.retrieval.filters": str(filters or {}),
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_generation(
    parent_span: trace.Span,
    model: str,
    prompt_tokens: int = None,
    completion_tokens: int = None,
    temperature: float = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing generation step.

    Usage:
        with trace_generation(span, "gpt-4", prompt_tokens=100) as gen_span:
            answer = llm.generate(prompt)
            gen_span.set_attribute("rag.generation.completion_tokens", len(answer))
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.generation",
        kind=SpanKind.CLIENT,
        attributes={
            "rag.generation.model": model,
            "rag.generation.prompt_tokens": prompt_tokens or 0,
            "rag.generation.completion_tokens": completion_tokens or 0,
            "rag.generation.temperature": temperature or 0.0,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_verification(
    parent_span: trace.Span,
    verification_type: str,
    threshold: float = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing verification step.

    Usage:
        with trace_verification(span, "faithfulness", threshold=0.85) as ver_span:
            score = check_faithfulness(answer, contexts)
            ver_span.set_attribute("rag.verification.score", score)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.verification",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.verification.type": verification_type,
            "rag.verification.threshold": threshold or 0.0,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_embedding(
    parent_span: trace.Span = None,
    model: str = None,
    batch_size: int = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing embedding generation.

    Usage:
        with trace_embedding(model="text-embedding-3-large", batch_size=32) as emb_span:
            embeddings = embed(texts)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.embedding",
        kind=SpanKind.CLIENT,
        attributes={
            "rag.embedding.model": model or "",
            "rag.embedding.batch_size": batch_size or 0,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_chunking(
    parent_span: trace.Span = None,
    strategy: str = None,
    chunk_size: int = None,
    overlap: int = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing document chunking.

    Usage:
        with trace_chunking(strategy="semantic", chunk_size=512) as chunk_span:
            chunks = chunker.chunk(document)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.chunking",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.chunking.strategy": strategy or "",
            "rag.chunking.chunk_size": chunk_size or 0,
            "rag.chunking.overlap": overlap or 0,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_ingestion(
    source_type: str,
    file_path: str = None,
    file_size: int = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing document ingestion.

    Usage:
        with trace_ingestion("pdf", "/path/to/doc.pdf", 1024*1024) as ing_span:
            result = ingest_document(file_path)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "rag.ingestion",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.ingestion.source_type": source_type,
            "rag.ingestion.file_path": file_path or "",
            "rag.ingestion.file_size": file_size or 0,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


# Metric instruments for custom metrics

def create_rag_metrics(meter: metrics.Meter = None) -> dict[str, Any]:
    """Create custom metric instruments for RAG pipeline."""
    if meter is None:
        meter = get_meter()

    return {
        # Counters
        "rag_requests": meter.create_counter(
            "rag.requests.total",
            description="Total RAG requests",
            unit="1",
        ),
        "rag_errors": meter.create_counter(
            "rag.errors.total",
            description="Total RAG errors",
            unit="1",
        ),
        "tokens_used": meter.create_counter(
            "rag.tokens.total",
            description="Total tokens used",
            unit="1",
        ),
        "cost_usd": meter.create_counter(
            "rag.cost.usd",
            description="Total cost in USD",
            unit="USD",
        ),

        # Histograms
        "retrieval_latency": meter.create_histogram(
            "rag.retrieval.latency",
            description="Retrieval latency",
            unit="s",
        ),
        "generation_latency": meter.create_histogram(
            "rag.generation.latency",
            description="Generation latency",
            unit="s",
        ),
        "verification_latency": meter.create_histogram(
            "rag.verification.latency",
            description="Verification latency",
            unit="s",
        ),
        "total_latency": meter.create_histogram(
            "rag.total.latency",
            description="Total RAG latency",
            unit="s",
        ),

        # Gauges (via callbacks)
    }


def record_rag_metrics(
    rag_metrics: dict[str, Any],
    stage: str,
    duration: float,
    tokens: dict[str, int] = None,
    cost: float = None,
    error: str = None,
    attributes: dict[str, Any] = None,
) -> None:
    """Record RAG metrics."""
    attrs = attributes or {}

    if stage == "retrieval":
        rag_metrics["retrieval_latency"].record(duration, attrs)
    elif stage == "generation":
        rag_metrics["generation_latency"].record(duration, attrs)
    elif stage == "verification":
        rag_metrics["verification_latency"].record(duration, attrs)

    if tokens:
        rag_metrics["tokens_used"].add(
            tokens.get("total", 0),
            {**attrs, "type": "total"},
        )
        rag_metrics["tokens_used"].add(
            tokens.get("prompt", 0),
            {**attrs, "type": "prompt"},
        )
        rag_metrics["tokens_used"].add(
            tokens.get("completion", 0),
            {**attrs, "type": "completion"},
        )

    if cost is not None:
        rag_metrics["cost_usd"].add(cost, attrs)

    if error:
        rag_metrics["rag_errors"].add(1, {**attrs, "error_type": error})
    else:
        rag_metrics["rag_requests"].add(1, attrs)
