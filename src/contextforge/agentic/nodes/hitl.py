"""
ContextForge HITL Node - Human-in-the-Loop Checkpoint

Pauses graph execution for human review when guardrails trigger.
Uses LangGraph checkpointer for persistence and resume capability.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from contextforge.agentic.state import (
    GuardrailViolation,
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.main import logger

# =============================================================================
# Models
# =============================================================================


@dataclass
class HITLPayload:
    """Payload sent to human reviewer."""

    request_id: str
    query: str
    answer: str
    citations: list[dict[str, Any]]
    violations: list[GuardrailViolation]
    guardrail_action: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HITLResponse:
    """Response from human reviewer."""

    action: Literal["approve", "reject", "modify", "escalate"]
    modified_answer: str | None = None
    reviewer_notes: str | None = None
    reviewer_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# Node Implementation
# =============================================================================


class HITLNode:
    """Human-in-the-loop checkpoint node."""

    def __init__(
        self,
        timeout_seconds: int = 3600,  # 1 hour default
        auto_approve_on_timeout: bool = False,
    ):
        self.timeout_seconds = timeout_seconds
        self.auto_approve_on_timeout = auto_approve_on_timeout

    async def __call__(self, state: RAGState) -> RAGState:
        """
        Execute HITL checkpoint.

        If HITL not required, passes through.
        If HITL required and no response yet, pauses (returns interrupt).
        If HITL response received, processes and continues.
        """
        start_time = time.perf_counter()

        hitl_required = state.get("hitl_required", False)
        hitl_response = state.get("hitl_response")

        if not hitl_required:
            # No HITL needed, pass through
            state = update_phase(state, "hitl", status="skipped")
            state = add_stream_event(state, "phase_complete", {"phase": "hitl", "status": "skipped"})
            return state

        if hitl_response is None:
            # First time hitting HITL - create payload and pause
            return await self._initiate_hitl(state)

        # HITL response received - process it
        return await self._process_hitl_response(state, hitl_response)

    async def _initiate_hitl(self, state: RAGState) -> RAGState:
        """Create HITL payload and trigger checkpoint."""
        # Build payload for human reviewer
        payload = HITLPayload(
            request_id=state["request_id"],
            query=state["query"],
            answer=state.get("answer", ""),
            citations=[
                {
                    "claim": c.claim,
                    "chunk_ids": [str(cid) for cid in c.chunk_ids],
                    "chunk_scores": c.chunk_scores,
                }
                for c in state.get("citations", [])
            ],
            violations=state.get("guardrail_violations", []),
            guardrail_action=state.get("guardrail_action", "hitl"),
            metadata={
                "verification": {
                    "confidence": state.get("verification", {}).confidence if state.get("verification") else None,
                    "factual_consistency": state.get("verification", {}).factual_consistency if state.get("verification") else None,
                },
                "latency_breakdown": {
                    "rewrite_ms": state.get("rewrite_latency_ms", 0),
                    "retrieve_ms": state.get("retrieval_latency_ms", 0),
                    "rerank_ms": state.get("rerank_latency_ms", 0),
                    "synthesize_ms": state.get("synthesis_latency_ms", 0),
                    "verify_ms": state.get("verify_latency_ms", 0),
                    "guardrail_ms": state.get("guardrail_latency_ms", 0),
                },
            },
        )

        # Store in state for checkpoint
        state["hitl_payload"] = payload.__dict__
        state["hitl_timestamp"] = datetime.utcnow()
        state["hitl_response"] = None  # Explicitly mark as waiting

        # Create checkpoint ID for resume
        checkpoint_id = f"hitl_{state['request_id']}_{uuid.uuid4().hex[:8]}"
        state["graph_checkpoint_id"] = checkpoint_id
        state["resume_from"] = "hitl"

        state = update_phase(state, "hitl", status="awaiting_review", checkpoint_id=checkpoint_id)
        state = add_stream_event(
            state,
            "phase_interrupt",
            {
                "phase": "hitl",
                "checkpoint_id": checkpoint_id,
                "payload": payload.__dict__,
                "message": "Human review required - graph paused at HITL checkpoint",
            },
        )

        logger.info(
            "hitl_initiated",
            checkpoint_id=checkpoint_id,
            request_id=state.get("request_id"),
            violations=len(payload.violations),
        )

        # This will cause LangGraph to pause at this node
        # The graph should be invoked with interrupt_before=["hitl"]
        # Or we raise a special interrupt signal
        from langgraph.types import interrupt

        # Trigger interrupt with payload for human reviewer
        interrupt(
            {
                "type": "hitl_required",
                "checkpoint_id": checkpoint_id,
                "payload": payload.__dict__,
            }
        )

        return state

    async def _process_hitl_response(self, state: RAGState, hitl_response: dict[str, Any]) -> RAGState:
        """Process human reviewer response."""
        start_time = time.perf_counter()
        response = HITLResponse(**hitl_response)

        state = update_phase(state, "hitl", status="resumed", reviewer_action=response.action)
        state = add_stream_event(
            state,
            "phase_resume",
            {"phase": "hitl", "action": response.action, "reviewer_id": response.reviewer_id},
        )

        logger.info(
            "hitl_resumed",
            action=response.action,
            reviewer_id=response.reviewer_id,
            request_id=state.get("request_id"),
        )

        if response.action == "approve":
            # Approved - continue with original answer
            state["hitl_required"] = False
            state["guardrail_action"] = "proceed"

        elif response.action == "modify" and response.modified_answer:
            # Modified - use reviewer's answer
            state["answer"] = response.modified_answer
            state["hitl_required"] = False
            state["guardrail_action"] = "proceed"
            # Add reviewer note as metadata
            if response.reviewer_notes:
                state.setdefault("phase_progress", {})["hitl_notes"] = response.reviewer_notes

        elif response.action == "reject":
            # Rejected - trigger rewrite
            state["hitl_required"] = False
            state["guardrail_action"] = "rewrite"
            state["rewrite_count"] = state.get("rewrite_count", 0)  # Don't increment, let verify decide
            if response.reviewer_notes:
                state.setdefault("phase_progress", {})["hitl_rejection_reason"] = response.reviewer_notes

        elif response.action == "escalate":
            # Escalated - block and flag for admin
            state["hitl_required"] = False
            state["guardrail_action"] = "block"
            state["error"] = "Escalated by human reviewer"
            state["error_node"] = "hitl"

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        state["guardrail_latency_ms"] = state.get("guardrail_latency_ms", 0) + latency_ms

        return state


# =============================================================================
# Helper Functions for External HITL Management
# =============================================================================


async def submit_hitl_response(
    checkpointer: Any,
    thread_id: str,
    checkpoint_id: str,
    response: HITLResponse,
) -> None:
    """
    Submit HITL response to resume a paused graph.

    This is called from an external API endpoint when reviewer responds.
    """
    # Get the checkpoint
    checkpoint = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})

    if not checkpoint:
        raise ValueError(f"No checkpoint found for thread {thread_id}")

    # Update checkpoint state with HITL response
    # This requires the checkpointer to support state updates
    # Implementation depends on checkpointer type (PostgresSaver vs MemorySaver)
    pass


def create_hitl_interrupt_payload(state: RAGState) -> dict[str, Any]:
    """Create standardized interrupt payload for HITL."""
    return {
        "type": "hitl_required",
        "checkpoint_id": state.get("checkpoint_id"),
        "request_id": state.get("request_id"),
        "query": state.get("query"),
        "answer": state.get("answer"),
        "violations": [
            {
                "type": v.violation_type,
                "severity": v.severity,
                "description": v.description,
                "suggested_action": v.suggested_action,
            }
            for v in state.get("guardrail_violations", [])
        ],
        "metadata": state.get("hitl_payload", {}).get("metadata", {}),
    }


# =============================================================================
# Factory Function
# =============================================================================


def create_hitl_node() -> HITLNode:
    """Factory to create HITL node with config."""
    return HITLNode(
        timeout_seconds=3600,
        auto_approve_on_timeout=False,
    )


# For LangGraph functional API
async def hitl_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_hitl_node()
    return await node(state)
