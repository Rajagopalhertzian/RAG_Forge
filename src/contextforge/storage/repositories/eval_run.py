"""
ContextForge Eval Run Repository

Repository for EvalRun model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.storage.database import EvalRun
from contextforge.storage.repositories.base import BaseRepository


class EvalRunRepository(BaseRepository[EvalRun]):
    """Repository for EvalRun operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, EvalRun)

    async def get_by_type(
        self,
        eval_type: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvalRun]:
        """Get eval runs by type."""
        result = await self.session.execute(
            select(EvalRun)
            .where(EvalRun.eval_type == eval_type)
            .order_by(EvalRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest_by_type(self, eval_type: str) -> EvalRun | None:
        """Get latest eval run by type."""
        result = await self.session.execute(
            select(EvalRun)
            .where(EvalRun.eval_type == eval_type)
            .order_by(EvalRun.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def mark_running(self, run_id: UUID) -> EvalRun | None:
        """Mark eval run as running."""
        from datetime import datetime
        return await self.update(run_id, status="running", started_at=datetime.utcnow())

    async def mark_completed(
        self,
        run_id: UUID,
        metrics: dict[str, Any],
    ) -> EvalRun | None:
        """Mark eval run as completed with metrics."""
        from datetime import datetime
        return await self.update(
            run_id,
            status="completed",
            metrics=metrics,
            completed_at=datetime.utcnow(),
        )

    async def mark_failed(self, run_id: UUID, error_message: str) -> EvalRun | None:
        """Mark eval run as failed."""
        from datetime import datetime
        return await self.update(
            run_id,
            status="failed",
            error_message=error_message,
            completed_at=datetime.utcnow(),
        )

    async def get_best_run(
        self,
        eval_type: str,
        metric: str,
        higher_is_better: bool = True,
    ) -> EvalRun | None:
        """Get the best eval run by a specific metric."""
        runs = await self.get_by_type(eval_type, limit=100)

        valid_runs = [
            r for r in runs
            if r.status == "completed" and metric in r.metrics
        ]

        if not valid_runs:
            return None

        return max(
            valid_runs,
            key=lambda r: r.metrics[metric],
        ) if higher_is_better else min(
            valid_runs,
            key=lambda r: r.metrics[metric],
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get eval run statistics."""
        by_type = await self.session.execute(
            select(EvalRun.eval_type, func.count(EvalRun.id))
            .group_by(EvalRun.eval_type)
        )

        by_status = await self.session.execute(
            select(EvalRun.status, func.count(EvalRun.id))
            .group_by(EvalRun.status)
        )

        return {
            "by_type": dict(by_type.all()),
            "by_status": dict(by_status.all()),
        }
