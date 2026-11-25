"""
ContextForge Rerank Node - Cross-Encoder Reranking

Uses Cohere rerank-v3 via AWS Bedrock for precision reranking.
Takes top-100 from hybrid search, returns top-10.
"""

from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.config import Config
from pydantic import BaseModel

from contextforge.agentic.state import (
    Chunk,
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.config import settings
from contextforge.main import logger

# =============================================================================
# Constants
# =============================================================================

COHERE_RERANK_MODEL = "cohere.rerank-v3-5:0"
DEFAULT_TOP_K = 10
DEFAULT_INPUT_K = 100


# =============================================================================
# Node Implementation
# =============================================================================


class RerankNode:
    """Cross-encoder reranking using Cohere rerank-v3 on Bedrock."""

    def __init__(
        self,
        model_id: str = COHERE_RERANK_MODEL,
        top_k: int = DEFAULT_TOP_K,
        region: str = "us-east-1",
        max_retries: int = 3,
    ):
        self.model_id = model_id
        self.top_k = top_k
        self.region = region

        # Bedrock runtime client with retries
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                retries={"max_attempts": max_retries, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=30,
            ),
        )

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute reranking."""
        start_time = time.perf_counter()

        retrieved_chunks = state.get("retrieved_chunks", [])
        top_k = state.get("top_k", self.top_k)

        if not retrieved_chunks:
            state["reranked_chunks"] = []
            state["rerank_latency_ms"] = 0
            return state

        state = update_phase(
            state,
            "rerank",
            input_count=len(retrieved_chunks),
            top_k=top_k,
        )
        state = add_stream_event(
            state,
            "phase_start",
            {"phase": "rerank", "input_chunks": len(retrieved_chunks), "top_k": top_k},
        )

        logger.info(
            "rerank_started",
            input_chunks=len(retrieved_chunks),
            top_k=top_k,
            request_id=state.get("request_id"),
        )

        try:
            # Limit input to configured max (Cohere has limits)
            input_chunks = retrieved_chunks[:DEFAULT_INPUT_K]

            # Prepare documents for reranking
            documents = [chunk.content for chunk in input_chunks]

            # Call Cohere rerank via Bedrock
            rerank_results = await self._rerank(state["query"], documents)

            # Map results back to chunks with rerank scores
            reranked_chunks = []
            for result in rerank_results.results[:top_k]:
                original_chunk = input_chunks[result.index]
                reranked_chunks.append(
                    Chunk(
                        id=original_chunk.id,
                        document_id=original_chunk.document_id,
                        content=original_chunk.content,
                        token_count=original_chunk.token_count,
                        score=original_chunk.score,  # Keep original fused score
                        rerank_score=result.relevance_score,
                        metadata=original_chunk.metadata,
                        embedding_model=original_chunk.embedding_model,
                        embedding_provider=original_chunk.embedding_provider,
                    )
                )

            state["reranked_chunks"] = reranked_chunks
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            state["rerank_latency_ms"] = latency_ms

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "rerank",
                    "latency_ms": latency_ms,
                    "output_chunks": len(reranked_chunks),
                    "top_rerank_score": reranked_chunks[0].rerank_score if reranked_chunks else 0,
                },
            )

            logger.info(
                "rerank_completed",
                output_chunks=len(reranked_chunks),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "rerank_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            # Fallback: use original retrieved chunks (top-k by fused score)
            # Create new Chunk instances with rerank_score set since Chunk is frozen
            fallback_chunks = []
            for chunk in retrieved_chunks[:top_k]:
                fallback_chunks.append(
                    Chunk(
                        id=chunk.id,
                        document_id=chunk.document_id,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        score=chunk.score,
                        rerank_score=chunk.score,  # Use original score as rerank score
                        metadata=chunk.metadata,
                        embedding_model=chunk.embedding_model,
                        embedding_provider=chunk.embedding_provider,
                    )
                )
            state["reranked_chunks"] = fallback_chunks
            state["rerank_latency_ms"] = latency_ms
            state = add_stream_event(
                state,
                "phase_error",
                {"phase": "rerank", "error": str(e), "fallback": True},
            )

        return state

    async def _rerank(self, query: str, documents: list[str]) -> Any:
        """Call Cohere rerank-v3 via Bedrock InvokeModel."""
        import json

        # Cohere rerank request format
        request_body = {
            "query": query,
            "documents": documents,
            "top_n": self.top_k,
            "return_documents": False,
        }

        # Invoke model
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        return RerankResponse(**response_body)


# =============================================================================
# Response Model
# =============================================================================


class RerankResult(BaseModel):
    """Single rerank result."""

    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    """Cohere rerank response."""

    results: list[RerankResult]
    id: str


# =============================================================================
# Factory Function
# =============================================================================


def create_rerank_node() -> RerankNode:
    """Factory to create rerank node with config."""
    return RerankNode(
        model_id=COHERE_RERANK_MODEL,
        top_k=10,
        region=settings.AWS_REGION,
    )


# For LangGraph functional API
async def rerank_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_rerank_node()
    return await node(state)
