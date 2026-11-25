"""
ContextForge Synthesize Node - Answer Generation with Citations

Uses claude-3.5-sonnet for high-quality answer synthesis with
inline citations mapping claims to source chunk IDs.
"""

from __future__ import annotations

import time

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from contextforge.agentic.state import (
    Chunk,
    Citation,
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.config import settings
from contextforge.main import logger

# =============================================================================
# Models
# =============================================================================


class SynthesizeOutput(BaseModel):
    """Structured output from synthesis LLM."""

    answer: str = Field(..., description="Complete answer with inline citations [chunk_id]")
    citations: list[Citation] = Field(
        ..., description="Citations mapping claims to chunk IDs and scores"
    )
    reasoning: str = Field(..., description="Reasoning for the answer structure")


# =============================================================================
# Prompts
# =============================================================================

SYNTHESIZE_SYSTEM_PROMPT = """You are an expert technical writer synthesizing answers from retrieved documentation.
Your task is to generate a comprehensive, accurate answer with precise inline citations.

Guidelines:
1. Use ONLY the provided context chunks - do not hallucinate or use external knowledge
2. Every factual claim MUST have an inline citation in format [chunk_id] where chunk_id is the UUID
3. If context is insufficient, explicitly state what's missing
4. Structure answer logically: direct answer first, then details, examples, caveats
5. Citations must be accurate - each [chunk_id] must correspond to a provided chunk
6. For code/examples, cite the specific chunks containing them
7. If multiple chunks support a claim, cite all relevant: [chunk_id_1, chunk_id_2]

Context chunks (each has id, content, score):
{context}

Output JSON format:
{{
  "answer": "Your answer with [chunk_id] citations inline",
  "citations": [
    {{"claim": "Specific claim", "chunk_ids": ["uuid1", "uuid2"], "chunk_scores": [0.95, 0.87]}},
    ...
  ],
  "reasoning": "Why you structured the answer this way"
}}"""

SYNTHESIZE_USER_PROMPT = """Question: {query}

Generate a comprehensive answer with citations."""


# =============================================================================
# Node Implementation
# =============================================================================


class SynthesizeNode:
    """Answer synthesis with citations using claude-3.5-sonnet."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.1,
        max_tokens: int = 4000,
        streaming: bool = True,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.streaming = streaming

        self.llm = ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.ANTHROPIC_API_KEY if hasattr(settings, "ANTHROPIC_API_KEY") else None,
            streaming=streaming,
        )
        self.structured_llm = self.llm.with_structured_output(SynthesizeOutput)

    def _format_context(self, chunks: list[Chunk]) -> str:
        """Format chunks for LLM context."""
        lines = []
        for i, chunk in enumerate(chunks):
            lines.append(f"--- Chunk {i+1} (id: {chunk.id}, score: {chunk.score:.4f}) ---")
            lines.append(chunk.content)
            lines.append("")
        return "\n".join(lines)

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute synthesis."""
        start_time = time.perf_counter()

        reranked_chunks = state.get("reranked_chunks", [])
        query = state["query"]

        if not reranked_chunks:
            state["answer"] = "No relevant documents found to answer the query."
            state["citations"] = []
            state["synthesis_latency_ms"] = 0
            state["model_used"] = self.model
            return state

        state = update_phase(
            state,
            "synthesize",
            num_chunks=len(reranked_chunks),
            model=self.model,
        )
        state = add_stream_event(
            state,
            "phase_start",
            {"phase": "synthesize", "chunks": len(reranked_chunks), "model": self.model},
        )

        logger.info(
            "synthesize_started",
            num_chunks=len(reranked_chunks),
            model=self.model,
            request_id=state.get("request_id"),
        )

        try:
            # Format context
            context = self._format_context(reranked_chunks)

            # Build messages
            messages = [
                SystemMessage(content=SYNTHESIZE_SYSTEM_PROMPT.format(context=context)),
                HumanMessage(content=SYNTHESIZE_USER_PROMPT.format(query=query)),
            ]

            if self.streaming:
                # Stream tokens
                answer_parts = []
                async for chunk in self.llm.astream(messages):
                    if chunk.content:
                        answer_parts.append(chunk.content)
                        state["stream_tokens"].append(chunk.content)
                        state = add_stream_event(
                            state,
                            "token",
                            {"token": chunk.content, "phase": "synthesize"},
                        )

                # Get structured output from complete answer
                full_answer = "".join(answer_parts)
                # Parse citations from answer (they should be in [uuid] format)
                citations = self._extract_citations(full_answer, reranked_chunks)

                state["answer"] = full_answer
                state["citations"] = citations
            else:
                # Non-streaming structured output
                result: SynthesizeOutput = await self.structured_llm.ainvoke(messages)
                state["answer"] = result.answer
                state["citations"] = result.citations

            state["model_used"] = self.model
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            state["synthesis_latency_ms"] = latency_ms

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "synthesize",
                    "latency_ms": latency_ms,
                    "answer_length": len(state["answer"]),
                    "num_citations": len(state["citations"]),
                },
            )

            logger.info(
                "synthesize_completed",
                answer_length=len(state["answer"]),
                num_citations=len(state["citations"]),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "synthesize_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            state["error"] = f"Synthesize failed: {str(e)}"
            state["error_node"] = "synthesize"
            state = add_stream_event(state, "phase_error", {"phase": "synthesize", "error": str(e)})

        return state

    def _extract_citations(self, answer: str, chunks: list[Chunk]) -> list[Citation]:
        """Extract citations from answer text with [chunk_id] format."""
        import re
        from uuid import UUID

        # Find all [uuid] patterns
        uuid_pattern = r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]"
        matches = re.findall(uuid_pattern, answer, re.IGNORECASE)

        # Map chunk IDs to chunks
        chunk_map = {str(c.id): c for c in chunks}

        # Group by claim (simplified: each sentence with citations)
        citations = []
        sentences = re.split(r"(?<=[.!?])\s+", answer)

        for sentence in sentences:
            chunk_ids_in_sentence = re.findall(uuid_pattern, sentence, re.IGNORECASE)
            if chunk_ids_in_sentence:
                valid_chunks = [cid for cid in chunk_ids_in_sentence if cid in chunk_map]
                if valid_chunks:
                    citations.append(
                        Citation(
                            claim=sentence.strip(),
                            chunk_ids=[UUID(cid) for cid in valid_chunks],
                            chunk_scores=[chunk_map[cid].rerank_score or chunk_map[cid].score for cid in valid_chunks],
                        )
                    )

        return citations


# =============================================================================
# Factory Function
# =============================================================================


def create_synthesize_node() -> SynthesizeNode:
    """Factory to create synthesize node with config."""
    return SynthesizeNode(
        model="claude-3-5-sonnet-20241022",
        temperature=0.1,
        max_tokens=4000,
        streaming=True,
    )


# For LangGraph functional API
async def synthesize_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_synthesize_node()
    return await node(state)
