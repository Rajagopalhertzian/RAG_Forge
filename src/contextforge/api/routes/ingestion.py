"""
ContextForge Ingestion API Routes

POST /ingest - Start ingestion job
GET /ingest/status/{job_id} - Get ingestion job status
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from contextforge.config import settings
from contextforge.ingestion import (
    ChunkerRegistry,
    EmbedderRegistry,
    IndexerRegistry,
    IngestionPipeline,
    IngestionResult,
    LoaderRegistry,
)
from contextforge.storage.database import get_session
from contextforge.storage.repositories import IngestionJobRepository

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


# =============================================================================
# Request/Response Models
# =============================================================================

class IngestRequest(BaseModel):
    """Request model for ingestion."""

    source_type: str = Field(..., description="Source type (pdf, markdown, notion, confluence, github, slack)")
    source_id: str = Field(..., description="Source identifier (file path, page ID, repo path, channel ID)")
    strategy: str | None = Field(None, description="Chunking strategy (semantic, hierarchical, code, fixed)")
    embedding_provider: str | None = Field(None, description="Embedding provider (openai, bedrock, local)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class IngestResponse(BaseModel):
    """Response model for ingestion."""

    job_id: UUID
    status: str
    message: str


class IngestStatusResponse(BaseModel):
    """Response model for ingestion status."""

    job_id: UUID
    status: str
    source_type: str
    source_id: str
    strategy: str
    embedding_provider: str
    embedding_model: str
    chunk_count: int
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str


class BatchIngestRequest(BaseModel):
    """Request model for batch ingestion."""

    items: list[IngestRequest] = Field(..., min_length=1, max_length=100)


class BatchIngestResponse(BaseModel):
    """Response model for batch ingestion."""

    job_ids: list[UUID]
    message: str


# =============================================================================
# Dependency: Get pipeline
# =============================================================================

def get_pipeline(
    source_type: str,
    strategy: str | None = None,
    embedding_provider: str | None = None,
    vector_store: str | None = None,
) -> IngestionPipeline:
    """Create ingestion pipeline from configuration."""
    return IngestionPipeline.from_config(
        source_type=source_type,
        strategy=strategy,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )


# =============================================================================
# Routes
# =============================================================================

@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    """
    Start an ingestion job for a single document.

    The job runs asynchronously. Use GET /ingest/status/{job_id} to check progress.
    """
    # Validate source type
    if LoaderRegistry.get(request.source_type) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source type: {request.source_type}. Available: {LoaderRegistry.list_sources()}",
        )

    # Validate strategy
    if request.strategy and ChunkerRegistry.get(request.strategy) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown chunking strategy: {request.strategy}. Available: {ChunkerRegistry.list_strategies()}",
        )

    # Validate embedding provider
    if request.embedding_provider and EmbedderRegistry.get(request.embedding_provider) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown embedding provider: {request.embedding_provider}. Available: {EmbedderRegistry.list_providers()}",
        )

    # Create pipeline
    pipeline = get_pipeline(
        source_type=request.source_type,
        strategy=request.strategy,
        embedding_provider=request.embedding_provider,
    )

    await pipeline.initialize()

    # Submit to background task
    job_id = await pipeline.ingest_async(
        request.source_id,
        strategy=request.strategy,
        embedding_provider=request.embedding_provider,
        metadata=request.metadata,
    )

    background_tasks.add_task(pipeline.close)

    return IngestResponse(
        job_id=job_id,
        status="pending",
        message="Ingestion job submitted. Check status with GET /ingest/status/{job_id}",
    )


@router.post("/ingest/sync", response_model=IngestionResult)
async def ingest_document_sync(
    request: IngestRequest,
) -> IngestionResult:
    """
    Ingest a document synchronously (waits for completion).

    Use for small documents or testing.
    """
    # Validate source type
    if LoaderRegistry.get(request.source_type) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source type: {request.source_type}. Available: {LoaderRegistry.list_sources()}",
        )

    # Create pipeline
    pipeline = get_pipeline(
        source_type=request.source_type,
        strategy=request.strategy,
        embedding_provider=request.embedding_provider,
    )

    await pipeline.initialize()

    try:
        result = await pipeline.ingest(
            request.source_id,
            strategy=request.strategy,
            embedding_provider=request.embedding_provider,
            metadata=request.metadata,
        )
        return result
    finally:
        await pipeline.close()


@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    strategy: str | None = Form(None),
    embedding_provider: str | None = Form(None),
    source_type: str = Form("pdf"),
    metadata: str = Form("{}"),
) -> IngestResponse:
    """
    Upload and ingest a file.

    Saves file temporarily and processes it.
    """
    import json
    import os
    import tempfile

    # Validate source type
    if LoaderRegistry.get(source_type) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source type: {source_type}. Available: {LoaderRegistry.list_sources()}",
        )

    # Check file size
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.INGESTION_MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_mb:.1f}MB > {settings.INGESTION_MAX_FILE_SIZE_MB}MB",
        )

    # Save to temp file
    suffix = os.path.splitext(file.filename)[1] if file.filename else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Parse metadata
        meta = json.loads(metadata) if metadata else {}

        # Create pipeline
        pipeline = get_pipeline(
            source_type=source_type,
            strategy=strategy,
            embedding_provider=embedding_provider,
        )

        await pipeline.initialize()

        # Submit to background task
        job_id = await pipeline.ingest_async(
            tmp_path,
            strategy=strategy,
            embedding_provider=embedding_provider,
            metadata=meta,
        )

        background_tasks.add_task(pipeline.close)
        background_tasks.add_task(os.unlink, tmp_path)

        return IngestResponse(
            job_id=job_id,
            status="pending",
            message="File upload complete. Ingestion job submitted.",
        )
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/status/{job_id}", response_model=IngestStatusResponse)
async def get_ingestion_status(job_id: UUID) -> IngestStatusResponse:
    """Get the status of an ingestion job."""
    async with get_session() as session:
        job_repo = IngestionJobRepository(session)
        job = await job_repo.get_by_id(job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Ingestion job not found: {job_id}")

        return IngestStatusResponse(
            job_id=job.id,
            status=job.status,
            source_type=job.source_type,
            source_id=job.source_id,
            strategy=job.strategy,
            embedding_provider=job.embedding_provider,
            embedding_model=job.embedding_model,
            chunk_count=job.chunk_count,
            error_message=job.error_message,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            created_at=job.created_at.isoformat(),
        )


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(
    request: BatchIngestRequest,
    background_tasks: BackgroundTasks,
) -> BatchIngestResponse:
    """
    Start multiple ingestion jobs.

    Each item is processed independently.
    """
    job_ids = []

    for item in request.items:
        # Validate each
        if LoaderRegistry.get(item.source_type) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown source type: {item.source_type}",
            )

        pipeline = get_pipeline(
            source_type=item.source_type,
            strategy=item.strategy,
            embedding_provider=item.embedding_provider,
        )

        await pipeline.initialize()

        job_id = await pipeline.ingest_async(
            item.source_id,
            strategy=item.strategy,
            embedding_provider=item.embedding_provider,
            metadata=item.metadata,
        )

        job_ids.append(job_id)
        background_tasks.add_task(pipeline.close)

    return BatchIngestResponse(
        job_ids=job_ids,
        message=f"Submitted {len(job_ids)} ingestion jobs",
    )


@router.get("/ingest/strategies")
async def list_strategies() -> dict[str, list[str]]:
    """List available chunking strategies."""
    return {"strategies": ChunkerRegistry.list_strategies()}


@router.get("/ingest/providers")
async def list_providers() -> dict[str, list[str]]:
    """List available embedding providers."""
    return {"providers": EmbedderRegistry.list_providers()}


@router.get("/ingest/sources")
async def list_sources() -> dict[str, list[str]]:
    """List available source types."""
    return {"sources": LoaderRegistry.list_sources()}


@router.get("/ingest/indexers")
async def list_indexers() -> dict[str, list[str]]:
    """List available vector indexers."""
    return {"indexers": IndexerRegistry.list_indexers()}
