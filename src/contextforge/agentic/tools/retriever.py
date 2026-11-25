"""
ContextForge Retriever Tool - Vector Search Implementation

Implements the vector_search and hybrid_search tools using the existing
pgvector infrastructure.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import text

from contextforge.ingestion.embedders import EmbedderRegistry
from contextforge.main import logger
from contextforge.storage.database import get_session

# =============================================================================
# Retriever Tool Implementation
# =============================================================================


class RetrieverTool:
    """Vector and hybrid search tool implementations."""

    def __init__(self) -> None:
        self.default_embedder = EmbedderRegistry.get("openai") or EmbedderRegistry.get("local")

    async def vector_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float = 0.0,
    ) -> dict[str, Any]:
        """
        Vector similarity search using pgvector HNSW.

        Args:
            query: Search query text
            top_k: Number of results to return
            filters: Metadata filters (source_type, date_range, document_ids)
            score_threshold: Minimum similarity score (0-1)

        Returns:
            Dict with results list
        """
        if not self.default_embedder:
            raise RuntimeError("No embedding provider available")

        start_time = time.perf_counter()

        # Generate query embedding
        embeddings = await self.default_embedder.embed([query])
        query_embedding = embeddings[0]

        # Build filter conditions
        filter_conditions = []
        filter_params = {}

        if filters:
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

        # Vector similarity search with cosine distance
        # 1 - (embedding <=> query_embedding) = cosine similarity
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
            AND 1 - (c.embedding <=> :query_embedding) >= :score_threshold
            ORDER BY c.embedding <=> :query_embedding
            LIMIT :k
        """)

        params = {
            "query_embedding": query_embedding,
            "k": top_k,
            "score_threshold": score_threshold,
            **filter_params,
        }

        async with get_session() as session:
            result = await session.execute(sql, params)
            rows = result.fetchall()

        chunks = []
        for row in rows:
            chunks.append({
                "id": str(row.id),
                "document_id": str(row.document_id),
                "chunk_index": row.chunk_index,
                "content": row.content,
                "token_count": row.token_count,
                "strategy": row.strategy,
                "metadata": row.metadata or {},
                "embedding_model": row.embedding_model,
                "embedding_provider": row.embedding_provider,
                "score": float(row.similarity),
            })

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "results": chunks,
            "latency_ms": latency_ms,
            "query": query,
            "top_k": top_k,
        }

    async def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        vector_weight: float = 0.5,
        bm25_weight: float = 0.5,
    ) -> dict[str, Any]:
        """
        Hybrid search: vector + BM25 with RRF fusion.

        Args:
            query: Search query text
            top_k: Number of results to return
            filters: Metadata filters
            vector_weight: Weight for vector search (not used in RRF, kept for compat)
            bm25_weight: Weight for BM25 search (not used in RRF, kept for compat)

        Returns:
            Dict with fused results
        """
        import time

        start_time = time.perf_counter()

        # Get vector results (k=100 for RRF pool)
        vector_results = await self.vector_search(
            query=query,
            top_k=100,
            filters=filters,
            score_threshold=0.0,
        )

        # Get BM25 results (k=100 for RRF pool)
        bm25_results = await self.bm25_search(
            query=query,
            top_k=100,
            filters=filters,
        )

        # Fuse with RRF
        fused = self._rrf_fuse(
            vector_results["results"],
            bm25_results["results"],
            rrf_k=60,
        )

        # Take top_k
        final_results = fused[:top_k]

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "results": final_results,
            "latency_ms": latency_ms,
            "query": query,
            "top_k": top_k,
            "vector_count": len(vector_results["results"]),
            "bm25_count": len(bm25_results["results"]),
        }

    async def bm25_search(
        self,
        query: str,
        top_k: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """BM25 keyword search using pgvector's tsvector."""
        import time

        start_time = time.perf_counter()

        # Build filter conditions
        filter_conditions = []
        filter_params = {}

        if filters:
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
            "k": top_k,
            **filter_params,
        }

        try:
            async with get_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()

            chunks = []
            for row in rows:
                chunks.append({
                    "id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "token_count": row.token_count,
                    "strategy": row.strategy,
                    "metadata": row.metadata or {},
                    "embedding_model": row.embedding_model,
                    "embedding_provider": row.embedding_provider,
                    "score": float(row.bm25_score),
                })

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            return {
                "results": chunks,
                "latency_ms": latency_ms,
            }
        except Exception as e:
            logger.warning("bm25_search_failed", error=str(e))
            return {"results": [], "latency_ms": int((time.perf_counter() - start_time) * 1000)}

    def _rrf_fuse(
        self,
        vector_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion."""
        vector_ranks = {r["id"]: i + 1 for i, r in enumerate(vector_results)}
        bm25_ranks = {r["id"]: i + 1 for i, r in enumerate(bm25_results)}

        all_ids = set(vector_ranks.keys()) | set(bm25_ranks.keys())
        result_map = {}
        for r in vector_results + bm25_results:
            if r["id"] not in result_map:
                result_map[r["id"]] = r

        fused = []
        for chunk_id in all_ids:
            result = result_map[chunk_id].copy()
            vector_rank = vector_ranks.get(chunk_id)
            bm25_rank = bm25_ranks.get(chunk_id)

            rrf_score = 0.0
            if vector_rank is not None:
                rrf_score += 1.0 / (rrf_k + vector_rank)
            if bm25_rank is not None:
                rrf_score += 1.0 / (rrf_k + bm25_rank)

            result["score"] = rrf_score
            result["rrf_score"] = rrf_score
            fused.append(result)

        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused


# =============================================================================
# Document Tools
# =============================================================================


class DocumentTool:
    """Document retrieval tools."""

    async def get_document(
        self,
        document_id: str,
        include_chunks: bool = False,
    ) -> dict[str, Any]:
        """Get document by ID."""
        from contextforge.storage.repositories.document import DocumentRepository

        async with get_session() as session:
            repo = DocumentRepository(session)
            document = await repo.get_by_id(UUID(document_id))

            if not document:
                return {"error": "Document not found", "document_id": document_id}

            result = {
                "id": str(document.id),
                "source_type": document.source_type,
                "source_id": document.source_id,
                "title": document.title,
                "content": document.content,
                "metadata": document.metadata_,
                "content_hash": document.content_hash,
                "chunk_count": document.chunk_count,
                "created_at": document.created_at.isoformat() if document.created_at else None,
                "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            }

            if include_chunks:
                from contextforge.storage.repositories.chunk import ChunkRepository
                chunk_repo = ChunkRepository(session)
                chunks = await chunk_repo.get_by_document_id(UUID(document_id))
                result["chunks"] = [
                    {
                        "id": str(c.id),
                        "chunk_index": c.chunk_index,
                        "content": c.content,
                        "token_count": c.token_count,
                        "strategy": c.strategy,
                        "metadata": c.metadata_,
                        "embedding_model": c.embedding_model,
                        "embedding_provider": c.embedding_provider,
                    }
                    for c in chunks
                ]

            return result

    async def list_documents(
        self,
        source_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List documents with pagination."""
        from contextforge.storage.repositories.document import DocumentRepository

        async with get_session() as session:
            repo = DocumentRepository(session)
            documents = await repo.list(
                source_type=source_type,
                limit=limit,
                offset=offset,
            )

            return {
                "documents": [
                    {
                        "id": str(d.id),
                        "source_type": d.source_type,
                        "source_id": d.source_id,
                        "title": d.title,
                        "chunk_count": d.chunk_count,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in documents
                ],
                "limit": limit,
                "offset": offset,
            }


# =============================================================================
# RAG Query Tool (Full Graph)
# =============================================================================


class RAGQueryTool:
    """Full agentic RAG query tool."""

    def __init__(self) -> None:
        from contextforge.agentic.graphs.rag_graph import get_rag_runner
        self.runner = get_rag_runner()

    async def rag_query(
        self,
        query: str,
        session_id: str | None = None,
        user_id: str | None = None,
        top_k: int = 10,
        retrieval_k: int = 100,
        filters: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Execute full agentic RAG query.

        Args:
            query: User query
            session_id: Session ID
            user_id: User ID
            top_k: Final results
            retrieval_k: Initial retrieval pool
            filters: Metadata filters
            stream: Whether to stream (not supported in tool, use API)

        Returns:
            Dict with answer, citations, verification, latency
        """
        if stream:
            # For streaming, return a special indicator
            # Actual streaming should use the API endpoint
            return {
                "error": "Streaming not supported in tool call. Use /api/v1/query/stream endpoint.",
                "stream_endpoint": "/api/v1/query/stream",
            }

        result = await self.runner.invoke(
            query=query,
            session_id=session_id,
            user_id=user_id,
            top_k=top_k,
            retrieval_k=retrieval_k,
            filters=filters,
        )

        return {
            "answer": result.get("answer", ""),
            "citations": [
                {
                    "claim": c.claim,
                    "chunk_ids": [str(cid) for cid in c.chunk_ids],
                    "chunk_scores": c.chunk_scores,
                }
                for c in result.get("citations", [])
            ],
            "verification": {
                "confidence": result.get("verification", {}).confidence if result.get("verification") else None,
                "factual_consistency": result.get("verification", {}).factual_consistency if result.get("verification") else None,
                "answer_completeness": result.get("verification", {}).answer_completeness if result.get("verification") else None,
                "hallucination_flags": result.get("verification", {}).hallucination_flags if result.get("verification") else [],
            } if result.get("verification") else None,
            "guardrail_action": result.get("guardrail_action"),
            "hitl_required": result.get("hitl_required"),
            "latency_ms": result.get("total_latency_ms"),
            "request_id": result.get("request_id"),
        }


# =============================================================================
# Tool Handler Factory
# =============================================================================


def create_tool_handlers() -> dict[str, Any]:
    """Create all tool handlers for registration."""
    retriever = RetrieverTool()
    document = DocumentTool()
    rag = RAGQueryTool()

    return {
        "vector_search": retriever.vector_search,
        "hybrid_search": retriever.hybrid_search,
        "get_document": document.get_document,
        "list_documents": document.list_documents,
        "rag_query": rag.rag_query,
    }


# =============================================================================
# Auto-register on Import
# =============================================================================

# Register tools when module is imported
try:
    from contextforge.agentic.tools.registry import register_retrieval_tools
    register_retrieval_tools(create_tool_handlers())
except Exception as e:
    logger.warning("tool_registration_failed", error=str(e))
