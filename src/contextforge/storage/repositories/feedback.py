"""
ContextForge Feedback Repository

Repository for Feedback model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.storage.database import Feedback
from contextforge.storage.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository[Feedback]):
    """Repository for Feedback operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Feedback)

    async def get_by_query(self, query_log_id: UUID) -> list[Feedback]:
        """Get all feedback for a query."""
        result = await self.session.execute(
            select(Feedback).where(Feedback.query_log_id == query_log_id)
        )
        return list(result.scalars().all())

    async def get_by_chunk(self, chunk_id: UUID) -> list[Feedback]:
        """Get all feedback for a chunk."""
        result = await self.session.execute(
            select(Feedback).where(Feedback.chunk_id == chunk_id)
        )
        return list(result.scalars().all())

    async def get_or_create(
        self,
        query_log_id: UUID,
        chunk_id: UUID,
        rating: int,
        feedback_type: str,
        comment: str | None = None,
    ) -> Feedback:
        """Get existing feedback or create new."""
        # Check if exists
        result = await self.session.execute(
            select(Feedback).where(
                Feedback.query_log_id == query_log_id,
                Feedback.chunk_id == chunk_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.rating = rating
            existing.feedback_type = feedback_type
            existing.comment = comment
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        # Create new
        return await self.create(
            query_log_id=query_log_id,
            chunk_id=chunk_id,
            rating=rating,
            feedback_type=feedback_type,
            comment=comment,
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get feedback statistics."""
        total = await self.count()

        by_rating = await self.session.execute(
            select(Feedback.rating, func.count(Feedback.id))
            .group_by(Feedback.rating)
        )

        by_type = await self.session.execute(
            select(Feedback.feedback_type, func.count(Feedback.id))
            .group_by(Feedback.feedback_type)
        )

        avg_rating = await self.session.execute(
            select(func.avg(Feedback.rating))
        )

        return {
            "total_feedback": total,
            "by_rating": dict(by_rating.all()),
            "by_type": dict(by_type.all()),
            "avg_rating": avg_rating.scalar_one() or 0.0,
        }
