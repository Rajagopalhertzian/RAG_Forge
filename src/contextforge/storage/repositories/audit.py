"""
ContextForge Audit Log Repository

Repository for AuditLog model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.storage.database import AuditLog
from contextforge.storage.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    """Repository for AuditLog operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, AuditLog)

    async def create(
        self,
        id: UUID,
        timestamp: Any,  # datetime
        client_id: str,
        session_id: str | None,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any] | None,
        latency_ms: float,
        status: str,
        error_message: str | None,
        transport: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuditLog:
        """Create audit log entry."""
        audit_log = AuditLog(
            id=id,
            timestamp=timestamp,
            client_id=client_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            transport=transport,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.session.add(audit_log)
        await self.session.flush()
        return audit_log

    async def get_by_client(self, client_id: str, limit: int = 100) -> list[AuditLog]:
        """Get audit logs by client."""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.client_id == client_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_tool(self, tool_name: str, limit: int = 100) -> list[AuditLog]:
        """Get audit logs by tool name."""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.tool_name == tool_name)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_stats(self) -> dict[str, Any]:
        """Get audit log statistics."""
        total = await self.session.execute(select(func.count(AuditLog.id)))
        by_status = await self.session.execute(
            select(AuditLog.status, func.count(AuditLog.id)).group_by(AuditLog.status)
        )
        by_tool = await self.session.execute(
            select(AuditLog.tool_name, func.count(AuditLog.id)).group_by(AuditLog.tool_name)
        )
        avg_latency = await self.session.execute(select(func.avg(AuditLog.latency_ms)))

        return {
            "total": total.scalar_one(),
            "by_status": dict(by_status.all()),
            "by_tool": dict(by_tool.all()),
            "avg_latency_ms": avg_latency.scalar_one() or 0,
        }
