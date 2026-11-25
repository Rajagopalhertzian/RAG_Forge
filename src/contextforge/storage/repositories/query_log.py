"""
ContextForge Query Log Repository

Repository for QueryLog model.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.storage.database import QueryLog
from contextforge.storage.repositories.base import BaseRepository


class QueryLogRepository(BaseRepository[QueryLog]):
    """Repository for QueryLog operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, QueryLog)

    async def get_by_user(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[QueryLog]:
        """Get queries by user."""
        result = await self.session.execute(
            select(QueryLog)
            .where(QueryLog.user_id == user_id)
            .order_by(QueryLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_session(
        self,
        session_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[QueryLog]:
        """Get queries by session."""
        result = await self.session.execute(
            select(QueryLog)
            .where(QueryLog.session_id == session_id)
            .order_by(QueryLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_queries(
        self,
        *,
        hours: int = 24,
        limit: int = 100,
    ) -> list[QueryLog]:
        """Get recent queries."""
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        result = await self.session.execute(
            select(QueryLog)
            .where(QueryLog.created_at >= cutoff)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_avg_latency(self, *, hours: int = 24) -> float:
        """Get average query latency in milliseconds."""
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        result = await self.session.execute(
            select(func.avg(QueryLog.latency_ms)).where(QueryLog.created_at >= cutoff)
        )
        return result.scalar_one() or 0.0

    async def get_stats(self, *, hours: int = 24) -> dict[str, Any]:
        """Get query statistics."""
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        total = await self.session.execute(
            select(func.count(QueryLog.id)).where(QueryLog.created_at >= cutoff)
        )
        avg_latency = await self.get_avg_latency(hours=hours)
        avg_results = await self.session.execute(
            select(func.avg(QueryLog.results_count)).where(QueryLog.created_at >= cutoff)
        )

        by_user = await self.session.execute(
            select(QueryLog.user_id, func.count(QueryLog.id))
            .where(QueryLog.created_at >= cutoff, QueryLog.user_id.is_not(None))
            .group_by(QueryLog.user_id)
        )

        return {
            "total_queries": total.scalar_one(),
            "avg_latency_ms": avg_latency,
            "avg_results": avg_results.scalar_one() or 0,
            "unique_users": len(by_user.all()),
        }
