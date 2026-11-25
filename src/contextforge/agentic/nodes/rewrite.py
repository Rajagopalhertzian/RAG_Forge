"""
ContextForge Rewrite Node - HyDE + Multi-Query Expansion

Uses gpt-4o-mini for cost-effective query rewriting.
Generates hypothetical document (HyDE) and multiple query variations.
"""

from __future__ import annotations

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from contextforge.agentic.state import (
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.config import settings
from contextforge.main import logger

# =============================================================================
# Models
# =============================================================================


class RewriteOutput(BaseModel):
    """Structured output from rewrite LLM."""

    rewritten_queries: list[str] = Field(
        ..., description="3-5 diverse query variations for retrieval"
    )
    hyde_document: str = Field(
        ..., description="Hypothetical document that would answer the query"
    )
    reasoning: str = Field(..., description="Why these queries were generated")


# =============================================================================
# Prompts
# =============================================================================

REWRITE_SYSTEM_PROMPT = """You are a query rewriting expert for a RAG system. Your task is to expand a user's query into multiple diverse variations and generate a hypothetical document (HyDE) that would perfectly answer the query.

Guidelines:
1. Generate 3-5 rewritten queries that capture different aspects/phrasings
2. Include synonyms, related terms, and different question structures
3. HyDE document should be detailed, factual, and directly answer the query
4. Keep queries concise but comprehensive
5. Consider the user's intent - are they looking for facts, explanations, comparisons, or procedures?

Output format: JSON with fields: rewritten_queries (list[str]), hyde_document (str), reasoning (str)"""

REWRITE_USER_PROMPT = """Original query: {query}

Context: This is for a technical documentation RAG system. The knowledge base contains:
- API documentation
- Technical guides and tutorials
- Architecture decision records
- Code examples and best practices
- Troubleshooting guides

Generate diverse query variations and a HyDE document."""


# =============================================================================
# Node Implementation
# =============================================================================


class RewriteNode:
    """Rewrite node using gpt-4o-mini for cost-effective query expansion."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ):
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.OPENAI_API_KEY,
            organization=settings.OPENAI_ORGANIZATION,
        )
        self.structured_llm = self.llm.with_structured_output(RewriteOutput)

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute rewrite node."""
        start_time = time.perf_counter()
        query = state["query"]
        rewrite_count = state.get("rewrite_count", 0)

        # Update phase
        state = update_phase(state, "rewrite", rewrite_attempt=rewrite_count + 1)
        state = add_stream_event(state, "phase_start", {"phase": "rewrite", "query": query})

        logger.info(
            "rewrite_started",
            query=query,
            rewrite_count=rewrite_count,
            request_id=state.get("request_id"),
        )

        try:
            # Build messages
            messages = [
                SystemMessage(content=REWRITE_SYSTEM_PROMPT),
                HumanMessage(content=REWRITE_USER_PROMPT.format(query=query)),
            ]

            # Call LLM with structured output
            result: RewriteOutput = await self.structured_llm.ainvoke(messages)

            # Update state
            state["rewritten_queries"] = result.rewritten_queries
            state["hyde_document"] = result.hyde_document
            state["rewrite_count"] = rewrite_count + 1

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "rewrite",
                    "latency_ms": latency_ms,
                    "num_queries": len(result.rewritten_queries),
                    "hyde_length": len(result.hyde_document),
                },
            )

            logger.info(
                "rewrite_completed",
                num_queries=len(result.rewritten_queries),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "rewrite_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            state["error"] = f"Rewrite failed: {str(e)}"
            state["error_node"] = "rewrite"
            state = add_stream_event(state, "phase_error", {"phase": "rewrite", "error": str(e)})

        return state


# =============================================================================
# Factory Function
# =============================================================================


def create_rewrite_node() -> RewriteNode:
    """Factory to create rewrite node with config."""
    return RewriteNode()


# For LangGraph functional API
async def rewrite_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_rewrite_node()
    return await node(state)
