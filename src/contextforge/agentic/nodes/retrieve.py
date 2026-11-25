"""
ContextForge Retrieve Node - Hybrid Search with RRF Fusion

Combines pgvector HNSW vector search (k=100) with BM25 keyword search,
then fuses results using Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.agentic.state import (
    Chunk,
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.config import settings
from contextforge.ingestion.embedders import EmbedderRegistry
from contextforge.main import logger
from contextforge.storage.database import get_session

# =============================================================================
# Constants
# =============================================================================

DEFAULT_RRF_K = 60  # RRF parameter
DEFAULT_VECTOR_K = 100
DEFAULT_BM25_K = 100


# =============================================================================
# Node Implementation
# =============================================================================


class RetrieveNode:
    """Hybrid retrieval node: pgvector HNSW + BM25 → RRF fusion."""

    def __init__(
        self,
        vector_k: int = DEFAULT_VECTOR_K,
        bm25_k: int = DEFAULT_BM25_K,
        rrf_k: int = DEFAULT_RRF_K,
    ):
        self.vector_k = vector_k
        self.bm25_k = bm25_k
        self.rrf_k = rrf_k

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute hybrid retrieval."""
        start_time = time.perf_counter()

        # Use rewritten queries or original query
        queries = state.get("rewritten_queries", []) or [state["query"]]
        filters = state.get("filters", {})
        retrieval_k = state.get("retrieval_k", self.vector_k)

        state = update_phase(
            state,
            "retrieve",
            num_queries=len(queries),
            vector_k=retrieval_k,
            bm25_k=self.bm25_k,
        )
        state = add_stream_event(
            state,
            "phase_start",
            {"phase": "retrieve", "queries": queries, "filters": filters},
        )

        logger.info(
            "retrieve_started",
            num_queries=len(queries),
            retrieval_k=retrieval_k,
            request_id=state.get("request_id"),
        )

        try:
            all_chunks: list[Chunk] = []

            async with get_session() as session:
                for query in queries:
                    # Vector search
                    vector_chunks = await self._vector_search(
                        session, query, retrieval_k, filters
                    )
                    # BM25 search
                    bm25_chunks = await self._bm25_search(
                        session, query, self.bm25_k, filters
                    )

                    # Fuse with RRF
                    fused = self._rrf_fuse(vector_chunks, bm25_chunks)
                    all_chunks.extend(fused)

            # Deduplicate by chunk ID, keep highest score
            deduped = self._deduplicate_chunks(all_chunks)
            # Sort by fused score descending
            deduped.sort(key=lambda c: c.score, reverse=True)
            # Take top retrieval_k
            final_chunks = deduped[:retrieval_k]

            state["retrieved_chunks"] = final_chunks
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            state["retrieval_latency_ms"] = latency_ms

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "retrieve",
                    "latency_ms": latency_ms,
                    "num_results": len(final_chunks),
                    "vector_results": len(vector_chunks) if 'vector_chunks' in locals() else 0,
                    "bm25_results": len(bm25_chunks) if 'bm25_chunks' in locals() else 0,
                },
            )

            logger.info(
                "retrieve_completed",
                num_results=len(final_chunks),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "retrieve_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            state["error"] = f"Retrieve failed: {str(e)}"
            state["error_node"] = "retrieve"
            state = add_stream_event(state, "phase_error", {"phase": "retrieve", "error": str(e)})

        return state

    async def _vector_search(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: dict[str, Any],
    ) -> list[Chunk]:
        """Execute pgvector HNSW similarity search."""
        # Get embedder (use default or configured)
        embedder = EmbedderRegistry.get("openai")  # Default
        if not embedder:
            # Fallback to local
            embedder = EmbedderRegistry.get("local")

        if not embedder:
            raise RuntimeError("No embedding provider available")

        # Generate query embedding
        embeddings = await embedder.embed([query])
        query_embedding = embeddings[0]

        # Build filter conditions
        filter_conditions = []
        filter_params = {}

        if filters.get("source_type"):
            filter_conditions.append("d.source_type = :source_type")
            filter_params["source_type"] = filters["source_type"]

        if filters.get("document_ids"):
            placeholders = ", ".join([f":doc_id_{i}" for i in range(len(filters["document_ids"]))])
            filter_conditions.append(f"d.id IN ({placeholders})")
            for i, doc_id in enumerate(filters["document_ids"]):
                filter_params[f"doc_id_{i}"] = doc_id

        if filters.get("date_from"):
            filter_conditions.append("d.created_at >= :date_from")
            filter_params["date_from"] = filters["date_from"]

        if filters.get("date_to"):
            filter_conditions.append("d.created_at <= :date_to")
            filter_params["date_to"] = filters["date_to"]

        where_clause = " AND ".join(filter_conditions) if filter_conditions else "1=1"

        # Vector similarity search with HNSW
        # Using cosine distance (1 - cosine_similarity)
        sql = text(f"""
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.content,
                c.token_count,
                c.strategy,
                c.metadata,
                c.embedding_model,
                c.embedding_provider,
                1 - (c.embedding <=> :query_embedding) AS similarity
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL
            AND {where_clause}
            ORDER BY c.embedding <=> :query_embedding
            LIMIT :k
        """)

        params = {
            "query_embedding": query_embedding,
            "k": k,
            **filter_params,
        }

        result = await session.execute(sql, params)
        rows = result.fetchall()

        chunks = []
        for row in rows:
            chunks.append(
                Chunk(
                    id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    token_count=row.token_count,
                    score=float(row.similarity),
                    metadata=row.metadata or {},
                    embedding_model=row.embedding_model,
                    embedding_provider=row.embedding_provider,
                )
            )

        return chunks

    async def _bm25_search(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: dict[str, Any],
    ) -> list[Chunk]:
        """Execute BM25 keyword search using pgvector's tsvector."""
        # Build filter conditions (same as vector search)
        filter_conditions = []
        filter_params = {}

        if filters.get("source_type"):
            filter_conditions.append("d.source_type = :source_type")
            filter_params["source_type"] = filters["source_type"]

        if filters.get("document_ids"):
            placeholders = ", ".join([f":doc_id_{i}" for i in range(len(filters["document_ids"]))])
            filter_conditions.append(f"d.id IN ({placeholders})")
            for i, doc_id in enumerate(filters["document_ids"]):
                filter_params[f"doc_id_{i}"] = doc_id

        if filters.get("date_from"):
            filter_conditions.append("d.created_at >= :date_from")
            filter_params["date_from"] = filters["date_from"]

        if filters.get("date_to"):
            filter_conditions.append("d.created_at <= :date_to")
            filter_params["date_to"] = filters["date_to"]

        where_clause = " AND ".join(filter_conditions) if filter_conditions else "1=1"

        # BM25 search using tsvector
        # Requires: ALTER TABLE chunks ADD COLUMN search_vector tsvector
        # CREATE INDEX ON chunks USING GIN(search_vector)
        # And a trigger to update search_vector on insert/update
        sql = text(f"""
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.content,
                c.token_count,
                c.strategy,
                c.metadata,
                c.embedding_model,
                c.embedding_provider,
                ts_rank_cd(c.search_vector, websearch_to_tsquery('english', :query)) AS bm25_score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.search_vector @@ websearch_to_tsquery('english', :query)
            AND {where_clause}
            ORDER BY bm25_score DESC
            LIMIT :k
        """)

        params = {
            "query": query,
            "k": k,
            **filter_params,
        }

        try:
            result = await session.execute(sql, params)
            rows = result.fetchall()

            chunks = []
            for row in rows:
                chunks.append(
                    Chunk(
                        id=row.id,
                        document_id=row.document_id,
                        content=row.content,
                        token_count=row.token_count,
                        score=float(row.bm25_score),
                        metadata=row.metadata or {},
                        embedding_model=row.embedding_model,
                        embedding_provider=row.embedding_provider,
                    )
                )

            return chunks
        except Exception as e:
            # BM25 might not be set up (no search_vector column)
            logger.warning("bm25_search_unavailable", error=str(e))
            return []

    def _rrf_fuse(
        self,
        vector_chunks: list[Chunk],
        bm25_chunks: list[Chunk],
    ) -> list[Chunk]:
        """
        Reciprocal Rank Fusion (RRF) to combine vector and BM25 results.

        RRF score = sum(1 / (k + rank_i)) for each result list
        where k is the RRF parameter (typically 60)
        """
        # Create rank maps
        vector_ranks = {c.id: i + 1 for i, c in enumerate(vector_chunks)}
        bm25_ranks = {c.id: i + 1 for i, c in enumerate(bm25_chunks)}

        # All unique chunk IDs
        all_ids = set(vector_ranks.keys()) | set(bm25_ranks.keys())

        # Build chunk lookup
        chunk_map = {}
        for c in vector_chunks + bm25_chunks:
            if c.id not in chunk_map:
                chunk_map[c.id] = c

        # Calculate RRF scores
        fused_chunks = []
        for chunk_id in all_ids:
            chunk = chunk_map[chunk_id]
            vector_rank = vector_ranks.get(chunk_id)
            bm25_rank = bm25_ranks.get(chunk_id)

            rrf_score = 0.0
            if vector_rank is not None:
                rrf_score += 1.0 / (self.rrf_k + vector_rank)
            if bm25_rank is not None:
                rrf_score += 1.0 / (self.rrf_k + bm25_rank)

            # Create new chunk with fused score
            fused_chunks.append(
                Chunk(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    score=rrf_score,
                    metadata=chunk.metadata,
                    embedding_model=chunk.embedding_model,
                    embedding_provider=chunk.embedding_provider,
                )
            )

        return fused_chunks

    def _deduplicate_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Deduplicate chunks by ID, keeping highest score."""
        seen: dict[UUID, Chunk] = {}
        for chunk in chunks:
            if chunk.id not in seen or chunk.score > seen[chunk.id].score:
                seen[chunk.id] = chunk
        return list(seen.values())


# =============================================================================
# Factory Function
# =============================================================================


def create_retrieve_node() -> RetrieveNode:
    """Factory to create retrieve node with config."""
    return RetrieveNode(
        vector_k=settings.PGVECTOR_HNSW_EF_SEARCH * 2,  # Dynamic based on HNSW config
        bm25_k=100,
        rrf_k=60,
    )


# For LangGraph functional API
async def retrieve_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_retrieve_node()
    return await node(state)
