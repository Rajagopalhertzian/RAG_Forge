"""
ContextForge Ingestion Job Repository

Repository for IngestionJob model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.storage.database import IngestionJob
from contextforge.storage.repositories.base import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJob]):
    """Repository for IngestionJob operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, IngestionJob)

    async def get_by_source(self, source_type: str, source_id: str) -> IngestionJob | None:
        """Get latest job by source."""
        result = await self.session.execute(
            select(IngestionJob)
            .where(
                IngestionJob.source_type == source_type,
                IngestionJob.source_id == source_id,
            )
            .order_by(IngestionJob.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def get_pending_jobs(self, limit: int = 100) -> list[IngestionJob]:
        """Get pending jobs for processing."""
        result = await self.session.execute(
            select(IngestionJob)
            .where(IngestionJob.status == "pending")
            .order_by(IngestionJob.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_processing_jobs(self) -> list[IngestionJob]:
        """Get currently processing jobs."""
        result = await self.session.execute(
            select(IngestionJob).where(IngestionJob.status == "processing")
        )
        return list(result.scalars().all())

    async def mark_processing(self, job_id: UUID) -> IngestionJob | None:
        """Mark job as processing."""
        from datetime import datetime
        return await self.update(
            job_id,
            status="processing",
            started_at=datetime.utcnow(),
        )

    async def mark_completed(
        self,
        job_id: UUID,
        document_id: UUID,
        chunk_count: int,
    ) -> IngestionJob | None:
        """Mark job as completed."""
        from datetime import datetime
        return await self.update(
            job_id,
            status="completed",
            document_id=document_id,
            chunk_count=chunk_count,
            completed_at=datetime.utcnow(),
        )

    async def mark_failed(self, job_id: UUID, error_message: str) -> IngestionJob | None:
        """Mark job as failed."""
        from datetime import datetime
        return await self.update(
            job_id,
            status="failed",
            error_message=error_message,
            completed_at=datetime.utcnow(),
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get job statistics."""
        by_status = await self.session.execute(
            select(IngestionJob.status, func.count(IngestionJob.id))
            .group_by(IngestionJob.status)
        )
        status_stats = dict(by_status.all())

        by_strategy = await self.session.execute(
            select(IngestionJob.strategy, func.count(IngestionJob.id))
            .group_by(IngestionJob.strategy)
        )
        strategy_stats = dict(by_strategy.all())

        total_chunks = await self.session.execute(
            select(func.sum(IngestionJob.chunk_count)).where(
                IngestionJob.status == "completed"
            )
        )

        return {
            "by_status": status_stats,
            "by_strategy": strategy_stats,
            "total_chunks_processed": total_chunks.scalar_one() or 0,
        }

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        progress: float | None = None,
        documents_processed: int | None = None,
        chunks_created: int | None = None,
        error: str | None = None,
    ) -> IngestionJob | None:
        """Update job status with optional progress and error."""
        from datetime import datetime

        update_data = {"status": status}

        if progress is not None:
            # Store progress in metadata since there's no progress column
            job = await self.get_by_id(job_id)
            if job:
                metadata = job.metadata_ or {}
                metadata["progress"] = progress
                if documents_processed is not None:
                    metadata["documents_processed"] = documents_processed
                if chunks_created is not None:
                    metadata["chunks_created"] = chunks_created
                update_data["metadata_"] = metadata

        if status == "processing" and not await self.get_by_id(job_id):
            update_data["started_at"] = datetime.utcnow()
        elif status in ("completed", "failed"):
            update_data["completed_at"] = datetime.utcnow()

        if error:
            update_data["error_message"] = error

        return await self.update(job_id, **update_data)
