"""
ContextForge Verify Node - LLM Judge for Quality Assurance

Uses gpt-4o-mini to verify answer quality:
- Confidence scoring
- Hallucination detection
- Factual consistency vs context
- Answer completeness
- Rewrite signal for low confidence
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from contextforge.agentic.state import (
    Chunk,
    RAGState,
    VerificationResult,
    add_stream_event,
    update_phase,
)
from contextforge.config import settings
from contextforge.main import logger

# =============================================================================
# Models
# =============================================================================


class VerifyOutput(BaseModel):
    """Structured output from verification LLM."""

    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence 0-1")
    hallucination_flags: list[str] = Field(
        ..., description="Specific hallucination concerns detected"
    )
    rewrite_signal: bool = Field(..., description="Whether to trigger rewrite loop")
    reasoning: str = Field(..., description="Detailed reasoning for scores")
    factual_consistency: float = Field(..., ge=0.0, le=1.0, description="Consistency with context 0-1")
    answer_completeness: float = Field(..., ge=0.0, le=1.0, description="Completeness vs query 0-1")


# =============================================================================
# Prompts
# =============================================================================

VERIFY_SYSTEM_PROMPT = """You are a quality assurance judge for a RAG system. Your task is to evaluate the generated answer against the source context and original query.

Evaluate on:
1. **Factual Consistency**: Does every claim in the answer have support in the context? (0-1)
2. **Answer Completeness**: Does the answer fully address the user's query? (0-1)
3. **Hallucination Detection**: Any claims not supported by context? List specific concerns.
3. **Overall Confidence**: Combined quality score (0-1)
4. **Rewrite Signal**: Should the system rewrite the query and retry? (true if confidence < 0.7 OR factual_consistency < 0.7 OR completeness < 0.6)

Context chunks:
{context}

Answer to evaluate:
{answer}

Citations provided:
{citations}

Output JSON with: confidence, hallucination_flags, rewrite_signal, reasoning, factual_consistency, answer_completeness"""

VERIFY_USER_PROMPT = """Original query: {query}

Evaluate the answer quality."""


# =============================================================================
# Node Implementation
# =============================================================================


class VerifyNode:
    """LLM judge verification using gpt-4o-mini."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        confidence_threshold: float = 0.7,
        consistency_threshold: float = 0.7,
        completeness_threshold: float = 0.6,
    ):
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.consistency_threshold = consistency_threshold
        self.completeness_threshold = completeness_threshold

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.OPENAI_API_KEY,
            organization=settings.OPENAI_ORGANIZATION,
        )
        self.structured_llm = self.llm.with_structured_output(VerifyOutput)

    def _format_context(self, chunks: list[Chunk]) -> str:
        """Format chunks for verification context."""
        lines = []
        for i, chunk in enumerate(chunks):
            lines.append(f"Chunk {i+1} (id: {chunk.id}, score: {chunk.score:.4f}):")
            lines.append(chunk.content[:500] + ("..." if len(chunk.content) > 500 else ""))
            lines.append("")
        return "\n".join(lines)

    def _format_citations(self, citations: list[Any]) -> str:
        """Format citations for verification."""
        lines = []
        for c in citations:
            chunk_ids = ", ".join(str(cid) for cid in c.chunk_ids)
            lines.append(f"- Claim: {c.claim[:100]}... | Chunks: [{chunk_ids}]")
        return "\n".join(lines) if lines else "None"

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute verification."""
        start_time = time.perf_counter()

        query = state["query"]
        answer = state.get("answer", "")
        reranked_chunks = state.get("reranked_chunks", [])
        citations = state.get("citations", [])

        if not answer:
            state["verification"] = VerificationResult(
                confidence=0.0,
                hallucination_flags=["No answer generated"],
                rewrite_signal=True,
                reasoning="Empty answer",
                factual_consistency=0.0,
                answer_completeness=0.0,
            )
            state["verify_latency_ms"] = 0
            return state

        state = update_phase(state, "verify", answer_length=len(answer))
        state = add_stream_event(
            state,
            "phase_start",
            {"phase": "verify", "model": self.model},
        )

        logger.info(
            "verify_started",
            answer_length=len(answer),
            request_id=state.get("request_id"),
        )

        try:
            # Format inputs
            context = self._format_context(reranked_chunks)
            citations_str = self._format_citations(citations)

            messages = [
                SystemMessage(content=VERIFY_SYSTEM_PROMPT.format(
                    context=context,
                    answer=answer,
                    citations=citations_str,
                )),
                HumanMessage(content=VERIFY_USER_PROMPT.format(query=query)),
            ]

            result: VerifyOutput = await self.structured_llm.ainvoke(messages)

            # Determine rewrite signal based on thresholds
            rewrite_signal = (
                result.confidence < self.confidence_threshold
                or result.factual_consistency < self.consistency_threshold
                or result.answer_completeness < self.completeness_threshold
                or result.rewrite_signal  # LLM's own judgment
            )

            verification = VerificationResult(
                confidence=result.confidence,
                hallucination_flags=result.hallucination_flags,
                rewrite_signal=rewrite_signal,
                reasoning=result.reasoning,
                factual_consistency=result.factual_consistency,
                answer_completeness=result.answer_completeness,
            )

            state["verification"] = verification
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            state["verify_latency_ms"] = latency_ms

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "verify",
                    "latency_ms": latency_ms,
                    "confidence": result.confidence,
                    "factual_consistency": result.factual_consistency,
                    "answer_completeness": result.answer_completeness,
                    "rewrite_signal": rewrite_signal,
                    "hallucination_flags": result.hallucination_flags,
                },
            )

            logger.info(
                "verify_completed",
                confidence=result.confidence,
                factual_consistency=result.factual_consistency,
                answer_completeness=result.answer_completeness,
                rewrite_signal=rewrite_signal,
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "verify_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            # Default to safe: trigger rewrite on verification failure
            state["verification"] = VerificationResult(
                confidence=0.5,
                hallucination_flags=[f"Verification error: {str(e)}"],
                rewrite_signal=True,
                reasoning="Verification failed, defaulting to rewrite",
                factual_consistency=0.5,
                answer_completeness=0.5,
            )
            state["verify_latency_ms"] = latency_ms
            state = add_stream_event(state, "phase_error", {"phase": "verify", "error": str(e)})

        return state


# =============================================================================
# Factory Function
# =============================================================================


def create_verify_node() -> VerifyNode:
    """Factory to create verify node with config."""
    return VerifyNode(
        model="gpt-4o-mini",
        confidence_threshold=0.7,
        consistency_threshold=0.7,
        completeness_threshold=0.6,
    )


# For LangGraph functional API
async def verify_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_verify_node()
    return await node(state)
