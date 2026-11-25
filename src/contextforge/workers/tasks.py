"""
ContextForge Celery Tasks

Async tasks for ingestion, maintenance, and evaluation.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from celery import shared_task

from contextforge.config import settings
from contextforge.ingestion import IngestionPipeline
from contextforge.storage.database import get_session
from contextforge.storage.repositories import DocumentRepository, IngestionJobRepository

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": settings.INGESTION_RETRY_ATTEMPTS},
)
def ingest_document_task(
    self,
    job_id: str,
    source_id: str,
    strategy: str,
    embedding_provider: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Celery task for document ingestion.

    Args:
        job_id: Ingestion job UUID
        source_id: Source identifier
        strategy: Chunking strategy
        embedding_provider: Embedding provider
        metadata: Additional metadata

    Returns:
        Dict with result info
    """
    import asyncio

    async def _run():
        async with get_session() as session:
            job_repo = IngestionJobRepository(session)
            job = await job_repo.get_by_id(UUID(job_id))

            if not job:
                return {"success": False, "error": f"Job not found: {job_id}"}

            # Update status to processing
            await job_repo.update_status(job_id, "processing", progress=0.1)

            try:
                # Create pipeline
                pipeline = IngestionPipeline.from_config(
                    source_type=job.source_type,
                    strategy=strategy,
                    embedding_provider=embedding_provider,
                )

                await pipeline.initialize()

                # Update progress
                await job_repo.update_status(job_id, "processing", progress=0.3)

                # Run ingestion
                result = await pipeline.ingest(
                    source_id,
                    strategy=strategy,
                    embedding_provider=embedding_provider,
                    metadata=metadata,
                )

                await job_repo.update_status(job_id, "processing", progress=0.9)

                await pipeline.close()

                if result.success:
                    return {
                        "success": True,
                        "document_id": str(result.document_id),
                        "chunk_count": result.chunk_count,
                    }
                else:
                    return {
                        "success": False,
                        "error": result.error_message,
                    }

            except Exception as e:
                logger.exception(f"Ingestion task failed for job {job_id}: {e}")
                await job_repo.update_status(job_id, "failed", error=str(e))
                return {"success": False, "error": str(e)}

    return asyncio.run(_run())


@shared_task
def reindex_document_task(document_id: str) -> dict[str, Any]:
    """
    Re-index a document (re-chunk and re-embed).

    Args:
        document_id: Document UUID

    Returns:
        Dict with result info
    """
    import asyncio

    async def _run():
        async with get_session() as session:
            doc_repo = DocumentRepository(session)
            document = await doc_repo.get_with_chunks(UUID(document_id))

            if not document:
                return {"success": False, "error": f"Document not found: {document_id}"}

            # TODO: Re-chunk and re-embed
            # This would require storing original content or re-loading from source

            return {"success": True, "message": "Re-indexing not yet implemented"}

    return asyncio.run(_run())


@shared_task
def reindex_stale_documents() -> dict[str, Any]:
    """
    Periodic task to re-index stale documents.

    Returns:
        Dict with result info
    """
    import asyncio
    from datetime import datetime, timedelta

    async def _run():
        async with get_session() as session:
            doc_repo = DocumentRepository(session)

            # Find documents older than 30 days that haven't been updated
            cutoff = datetime.utcnow() - timedelta(days=30)

            # This is a placeholder - would need to track last_indexed_at
            # For now, just return success

            return {
                "success": True,
                "message": "Reindex stale documents - not yet implemented",
                "checked": 0,
                "reindexed": 0,
            }

    return asyncio.run(_run())


@shared_task
def cleanup_old_jobs() -> dict[str, Any]:
    """
    Periodic task to clean up old ingestion jobs.

    Returns:
        Dict with result info
    """
    import asyncio
    from datetime import datetime, timedelta

    async def _run():
        async with get_session() as session:
            job_repo = IngestionJobRepository(session)

            # Delete jobs older than 90 days that are completed/failed
            cutoff = datetime.utcnow() - timedelta(days=90)

            # This would be a raw SQL delete for performance
            # For now, return placeholder

            return {
                "success": True,
                "message": "Cleanup old jobs - not yet implemented",
                "deleted": 0,
            }

    return asyncio.run(_run())


@shared_task
def run_chunking_evaluation(
    dataset: str,
    strategies: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run chunking evaluation on a dataset.

    Args:
        dataset: Dataset name/path
        strategies: List of strategies to evaluate

    Returns:
        Dict with evaluation results
    """
    import asyncio

    async def _run():
        # TODO: Implement evaluation
        return {
            "success": True,
            "message": "Chunking evaluation not yet implemented",
            "results": {},
        }

    return asyncio.run(_run())


@shared_task
def run_embedding_evaluation(
    dataset: str,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run embedding evaluation on a dataset.

    Args:
        dataset: Dataset name/path
        providers: List of providers to evaluate

    Returns:
        Dict with evaluation results
    """
    import asyncio

    async def _run():
        # TODO: Implement evaluation
        return {
            "success": True,
            "message": "Embedding evaluation not yet implemented",
            "results": {},
        }

    return asyncio.run(_run())
