"""
ContextForge Chunk Repository

Repository for Chunk model with vector similarity search.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from contextforge.storage.database import Chunk
from contextforge.storage.repositories.base import BaseRepository


class ChunkRepository(BaseRepository[Chunk]):
    """Repository for Chunk operations with vector search."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Chunk)

    async def get_by_document(self, document_id: UUID) -> list[Chunk]:
        """Get all chunks for a document."""
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())

    async def get_with_document(self, id: UUID) -> Chunk | None:
        """Get chunk with document loaded."""
        result = await self.session.execute(
            select(Chunk)
            .options(selectinload(Chunk.document))
            .where(Chunk.id == id)
        )
        return result.scalar_one_or_none()

    async def vector_search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filter_document_ids: list[UUID] | None = None,
        filter_metadata: dict[str, Any] | None = None,
        min_similarity: float = 0.0,
    ) -> list[tuple[Chunk, float]]:
        """
        Perform vector similarity search using pgvector HNSW index.

        Returns list of (Chunk, similarity_score) tuples.
        """
        # Build the query
        query = select(
            Chunk,
            (1 - Chunk.embedding.cosine_distance(query_embedding)).label("similarity")
        ).where(
            Chunk.embedding.is_not(None),
            (1 - Chunk.embedding.cosine_distance(query_embedding)) >= min_similarity,
        )

        # Apply document ID filter
        if filter_document_ids:
            query = query.where(Chunk.document_id.in_(filter_document_ids))

        # Apply metadata filter (JSONB)
        if filter_metadata:
            for key, value in filter_metadata.items():
                query = query.where(Chunk.metadata_[key].astext == str(value))

        # Order by similarity (highest first) and limit
        query = query.order_by(text("similarity DESC")).limit(top_k)

        result = await self.session.execute(query)
        return [(row.Chunk, row.similarity) for row in result.all()]

    async def hybrid_search(
        self,
        query_embedding: list[float],
        query_text: str,
        *,
        top_k: int = 10,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        filter_document_ids: list[UUID] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """
        Perform hybrid search combining vector and full-text search.

        Returns list of (Chunk, combined_score) tuples.
        """
        # This is a simplified hybrid search
        # In production, you'd use tsvector for full-text search
        vector_results = await self.vector_search(
            query_embedding,
            top_k=top_k * 2,
            filter_document_ids=filter_document_ids,
        )

        # Score and re-rank
        scored_chunks = []
        for chunk, vector_score in vector_results:
            # Simple text matching score
            text_score = 1.0 if query_text.lower() in chunk.content.lower() else 0.0
            combined_score = vector_weight * vector_score + text_weight * text_score
            scored_chunks.append((chunk, combined_score))

        # Sort by combined score
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks[:top_k]

    async def get_chunks_by_strategy(
        self,
        strategy: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Chunk]:
        """Get chunks by chunking strategy."""
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.strategy == strategy)
            .order_by(Chunk.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_embedding_stats(self) -> dict[str, Any]:
        """Get embedding statistics."""
        # Count chunks with/without embeddings
        with_embedding = await self.session.execute(
            select(func.count(Chunk.id)).where(Chunk.embedding.is_not(None))
        )
        without_embedding = await self.session.execute(
            select(func.count(Chunk.id)).where(Chunk.embedding.is_(None))
        )

        # Count by provider/model
        by_provider = await self.session.execute(
            select(Chunk.embedding_provider, Chunk.embedding_model, func.count(Chunk.id))
            .where(Chunk.embedding.is_not(None))
            .group_by(Chunk.embedding_provider, Chunk.embedding_model)
        )

        return {
            "with_embedding": with_embedding.scalar_one(),
            "without_embedding": without_embedding.scalar_one(),
            "by_provider_model": {
                f"{p}/{m}": c for p, m, c in by_provider.all()
            },
        }

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete all chunks for a document."""
        result = await self.session.execute(
            select(Chunk).where(Chunk.document_id == document_id)
        )
        chunks = list(result.scalars().all())
        for chunk in chunks:
            await self.session.delete(chunk)
        await self.session.flush()
        return len(chunks)

    async def search_by_text(self, query: str, limit: int = 10) -> list[Chunk]:
        """Search chunks by text content (simple ILIKE search)."""
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.content.ilike(f"%{query}%"))
            .order_by(Chunk.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_document_id(self, document_id: UUID) -> list[Chunk]:
        """Get all chunks for a document (alias for get_by_document)."""
        return await self.get_by_document(document_id)
