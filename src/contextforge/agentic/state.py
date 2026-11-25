"""
ContextForge Agentic RAG State Definition

TypedDict-based state for LangGraph StateGraph with all fields required
for the 7-node agentic RAG pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

from langgraph.graph import add_messages

# =============================================================================
# Core Data Types
# =============================================================================


@dataclass(frozen=True)
class Chunk:
    """Retrieved chunk with metadata and citation info."""

    id: UUID
    document_id: UUID
    content: str
    token_count: int
    score: float
    rerank_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding_model: str | None = None
    embedding_provider: str | None = None


@dataclass(frozen=True)
class Citation:
    """Citation linking a claim to source chunks."""

    claim: str
    chunk_ids: list[UUID]
    chunk_scores: list[float]


@dataclass(frozen=True)
class GuardrailViolation:
    """Guardrail violation details."""

    violation_type: Literal["pii", "toxicity", "hallucination", "policy"]
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    detected_content: str | None = None
    suggested_action: Literal["block", "rewrite", "review", "allow"] = "review"


@dataclass(frozen=True)
class VerificationResult:
    """LLM judge verification output."""

    confidence: float  # 0.0 - 1.0
    hallucination_flags: list[str]
    rewrite_signal: bool
    reasoning: str
    factual_consistency: float
    answer_completeness: float


# =============================================================================
# RAG State (TypedDict for LangGraph)
# =============================================================================


class RAGState(TypedDict, total=False):
    """
    Complete state for the agentic RAG graph.

    Fields flow through 7 nodes: rewrite → retrieve → rerank → synthesize →
    verify → guardrail → hitl (conditional)

    All fields are optional (total=False) to allow partial updates at each node.
    """

    # ---- Input ----
    query: str
    """Original user query"""
    session_id: str | None
    """Session identifier for conversation context"""
    user_id: str | None
    """User identifier for personalization and audit"""
    top_k: int
    """Final number of results to return (default: 10)"""
    retrieval_k: int
    """Initial retrieval pool size (default: 100)"""
    filters: dict[str, Any]
    """Metadata filters (source_type, date_range, etc.)"""
    rewrite_count: int
    """Number of rewrite attempts (for loop detection)"""
    max_rewrites: int
    """Maximum rewrite attempts before giving up (default: 3)"""

    # ---- Rewrite Node Output ----
    rewritten_queries: list[str]
    """HyDE + multi-query expanded queries"""
    hyde_document: str | None
    """Hypothetical document from HyDE"""

    # ---- Retrieve Node Output ----
    retrieved_chunks: list[Chunk]
    """Chunks from hybrid search (vector + BM25 → RRF)"""
    retrieval_latency_ms: int
    """Time spent in retrieval"""

    # ---- Rerank Node Output ----
    reranked_chunks: list[Chunk]
    """Top-k chunks after cross-encoder reranking"""
    rerank_latency_ms: int
    """Time spent in reranking"""

    # ---- Synthesize Node Output ----
    answer: str
    """Final synthesized answer"""
    citations: list[Citation]
    """Citations mapping claims to chunk IDs"""
    synthesis_latency_ms: int
    """Time spent in synthesis"""
    model_used: str
    """Model used for synthesis (e.g., claude-3.5-sonnet)"""

    # ---- Verify Node Output ----
    verification: VerificationResult | None
    """LLM judge verification result"""
    verify_latency_ms: int
    """Time spent in verification"""

    # ---- Guardrail Node Output ----
    guardrail_violations: list[GuardrailViolation]
    """Any guardrail violations detected"""
    guardrail_action: Literal["proceed", "rewrite", "hitl", "block"]
    """Action determined by guardrails"""
    guardrail_latency_ms: int
    """Time spent in guardrails"""

    # ---- HITL Node ----
    hitl_required: bool
    """Whether human-in-the-loop is required"""
    hitl_reason: str | None
    """Reason for HITL requirement"""
    hitl_payload: dict[str, Any] | None
    """Payload for human reviewer"""
    hitl_response: dict[str, Any] | None
    """Human reviewer response (after resume)"""
    hitl_timestamp: datetime | None
    """When HITL was triggered"""

    # ---- Streaming / Progress ----
    current_phase: Literal[
        "rewrite",
        "retrieve",
        "rerank",
        "synthesize",
        "verify",
        "guardrail",
        "hitl",
        "complete",
        "error",
    ]
    """Current phase for streaming updates"""
    phase_progress: dict[str, Any]
    """Progress details for current phase"""
    stream_tokens: list[str]
    """Streamed tokens from synthesis"""
    stream_events: list[dict[str, Any]]
    """All stream events for replay"""

    # ---- Error Handling ----
    error: str | None
    """Error message if graph failed"""
    error_node: str | None
    """Node where error occurred"""
    retry_count: int
    """Number of retries attempted"""

    # ---- Metadata ----
    request_id: str
    """Unique request identifier"""
    started_at: datetime
    """Graph execution start time"""
    completed_at: datetime | None
    """Graph execution completion time"""
    total_latency_ms: int | None
    """Total execution time in milliseconds"""

    # ---- Checkpoint / Resume ----
    graph_checkpoint_id: str | None
    """Checkpoint ID for resume capability"""
    resume_from: str | None
    """Node to resume from after HITL"""

    # LangGraph messages for potential future chat history
    messages: Annotated[list[Any], add_messages]
    """Message history (for conversational RAG)"""


# =============================================================================
# Helper Functions
# =============================================================================


def create_initial_state(
    query: str,
    session_id: str | None = None,
    user_id: str | None = None,
    top_k: int = 10,
    retrieval_k: int = 100,
    filters: dict[str, Any] | None = None,
    max_rewrites: int = 3,
    request_id: str | None = None,
) -> RAGState:
    """Create initial state for a new RAG query."""
    import uuid
    from datetime import datetime

    return RAGState(
        query=query,
        session_id=session_id,
        user_id=user_id,
        top_k=top_k,
        retrieval_k=retrieval_k,
        filters=filters or {},
        rewrite_count=0,
        max_rewrites=max_rewrites,
        rewritten_queries=[],
        hyde_document=None,
        retrieved_chunks=[],
        retrieval_latency_ms=0,
        reranked_chunks=[],
        rerank_latency_ms=0,
        answer="",
        citations=[],
        synthesis_latency_ms=0,
        model_used="",
        verification=None,
        verify_latency_ms=0,
        guardrail_violations=[],
        guardrail_action="proceed",
        guardrail_latency_ms=0,
        hitl_required=False,
        hitl_reason=None,
        hitl_payload=None,
        hitl_response=None,
        hitl_timestamp=None,
        current_phase="rewrite",
        phase_progress={},
        stream_tokens=[],
        stream_events=[],
        error=None,
        error_node=None,
        retry_count=0,
        request_id=request_id or str(uuid.uuid4()),
        started_at=datetime.utcnow(),
        completed_at=None,
        total_latency_ms=None,
        graph_checkpoint_id=None,
        resume_from=None,
        messages=[],
    )


def update_phase(state: RAGState, phase: RAGState[current_phase], **progress: Any) -> RAGState:
    """Update current phase and progress."""
    state["current_phase"] = phase
    state["phase_progress"] = progress
    return state


def add_stream_event(state: RAGState, event_type: str, data: dict[str, Any]) -> RAGState:
    """Add a streaming event to the state."""
    event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "phase": state.get("current_phase", "unknown"),
        "data": data,
    }
    state.setdefault("stream_events", []).append(event)
    return state
