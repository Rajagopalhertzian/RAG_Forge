"""
ContextForge Document Repository

Repository for Document model with specialized queries.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from contextforge.storage.database import Document
from contextforge.storage.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    """Repository for Document operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def get_by_source(self, source_type: str, source_id: str) -> Document | None:
        """Get document by source type and ID."""
        result = await self.session.execute(
            select(Document).where(
                Document.source_type == source_type,
                Document.source_id == source_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_with_chunks(self, id: UUID) -> Document | None:
        """Get document with chunks loaded."""
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: str) -> Document | None:
        """Get document by content hash."""
        result = await self.session.execute(
            select(Document).where(Document.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def search_by_title(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Document]:
        """Search documents by title (full-text search)."""
        # Using ILIKE for simple search; could be upgraded to tsvector
        result = await self.session.execute(
            select(Document)
            .where(Document.title.ilike(f"%{query}%"))
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(
        self,
        *,
        days: int = 7,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Document]:
        """Get recently created documents."""
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        result = await self.session.execute(
            select(Document)
            .where(Document.created_at >= cutoff)
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_stats(self) -> dict[str, Any]:
        """Get document statistics."""
        total = await self.count()
        by_source = await self.session.execute(
            select(Document.source_type, func.count(Document.id))
            .group_by(Document.source_type)
        )
        source_stats = dict(by_source.all())

        return {
            "total_documents": total,
            "by_source": source_stats,
        }

    async def get_collections(self) -> list[dict[str, Any]]:
        """Get distinct collections from document metadata."""
        from datetime import datetime

        total = await self.count()

        result = await self.session.execute(
            select(
                Document.metadata_["collection"].astext.label("collection"),
                func.count(Document.id).label("count"),
                func.min(Document.created_at).label("created_at"),
            )
            .where(Document.metadata_["collection"].is_not(None))
            .group_by(Document.metadata_["collection"].astext)
            .order_by(func.count(Document.id).desc())
        )

        collections = []
        for row in result.all():
            collections.append({
                "name": row.collection or "default",
                "description": f"Collection: {row.collection or 'default'}",
                "count": row.count,
                "created_at": row.created_at or datetime.utcnow(),
            })

        # Always include default collection if no collections exist
        if not collections:
            collections.append({
                "name": "default",
                "description": "Default document collection",
                "count": total,
                "created_at": datetime.utcnow(),
            })

        return collections
