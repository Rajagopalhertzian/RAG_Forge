"""
ContextForge Graph Edges - Conditional Routing Logic

Defines conditional edges for the agentic RAG graph:
- Rewrite loop on low confidence
- HITL on guardrail violations
- Error handling
"""

from __future__ import annotations

from typing import Literal

from contextforge.agentic.state import RAGState
from contextforge.main import logger

# =============================================================================
# Edge Functions (for LangGraph conditional_edges)
# =============================================================================


def should_rewrite(state: RAGState) -> Literal["rewrite", "retrieve"]:
    """
    Decide whether to loop back to rewrite or proceed to retrieve.

    Called after verify node.
    """
    verification = state.get("verification")
    rewrite_count = state.get("rewrite_count", 0)
    max_rewrites = state.get("max_rewrites", 3)

    if not verification:
        logger.warning("no_verification_default_rewrite", request_id=state.get("request_id"))
        return "rewrite"

    # Check rewrite signal from verification
    if verification.rewrite_signal:
        if rewrite_count >= max_rewrites:
            logger.info(
                "max_rewrites_reached_proceed_to_retrieve",
                rewrite_count=rewrite_count,
                max_rewrites=max_rewrites,
                request_id=state.get("request_id"),
            )
            return "retrieve"

        logger.info(
            "rewrite_signal_triggered",
            rewrite_count=rewrite_count + 1,
            confidence=verification.confidence,
            factual_consistency=verification.factual_consistency,
            answer_completeness=verification.answer_completeness,
            request_id=state.get("request_id"),
        )
        return "rewrite"

    # No rewrite needed
    return "retrieve"


def should_hitl(state: RAGState) -> Literal["hitl", "complete"]:
    """
    Decide whether to go to HITL or complete.

    Called after guardrail node.
    """
    guardrail_action = state.get("guardrail_action", "proceed")
    hitl_required = state.get("hitl_required", False)

    # Check if guardrails require HITL
    if guardrail_action == "hitl" or hitl_required:
        state["hitl_required"] = True
        logger.info(
            "hitl_required",
            guardrail_action=guardrail_action,
            violations=len(state.get("guardrail_violations", [])),
            request_id=state.get("request_id"),
        )
        return "hitl"

    # Check for block action
    if guardrail_action == "block":
        logger.warning(
            "guardrail_block",
            violations=[v.description for v in state.get("guardrail_violations", [])],
            request_id=state.get("request_id"),
        )
        state["error"] = "Blocked by guardrails"
        state["error_node"] = "guardrail"
        return "complete"  # Will end with error

    # Check for rewrite action from guardrails
    if guardrail_action == "rewrite":
        logger.info(
            "guardrail_rewrite_signal",
            request_id=state.get("request_id"),
        )
        return "rewrite"

    # Proceed to completion
    return "complete"


def should_continue_after_hitl(state: RAGState) -> Literal["rewrite", "complete"]:
    """
    Decide next step after HITL response.

    Called after hitl node.
    """
    guardrail_action = state.get("guardrail_action", "proceed")
    hitl_response = state.get("hitl_response")

    if not hitl_response:
        # Still waiting for HITL (shouldn't happen in normal flow)
        logger.warning("hitl_no_response", request_id=state.get("request_id"))
        return "complete"

    action = hitl_response.get("action", "approve")

    if action == "rewrite" or guardrail_action == "rewrite":
        logger.info("hitl_triggered_rewrite", request_id=state.get("request_id"))
        return "rewrite"

    if action == "block" or guardrail_action == "block":
        logger.warning("hitl_blocked", request_id=state.get("request_id"))
        state["error"] = "Blocked by human reviewer"
        state["error_node"] = "hitl"
        return "complete"

    # Approve or modify - complete
    return "complete"


def route_on_error(state: RAGState) -> Literal["rewrite", "hitl", "complete"]:
    """
    Route based on error state.

    Can be used as a general error handler edge.
    """
    error = state.get("error")
    error_node = state.get("error_node")
    retry_count = state.get("retry_count", 0)
    max_retries = 3

    if not error:
        return "complete"

    logger.error(
        "graph_error",
        error=error,
        error_node=error_node,
        retry_count=retry_count,
        request_id=state.get("request_id"),
    )

    # Retry logic based on error node
    if error_node in ("rewrite", "retrieve", "rerank") and retry_count < max_retries:
        state["retry_count"] = retry_count + 1
        logger.info("retrying_from_error", retry_count=retry_count + 1, request_id=state.get("request_id"))
        return "rewrite"  # Restart from rewrite

    if error_node in ("verify", "guardrail") and retry_count < max_retries:
        state["retry_count"] = retry_count + 1
        return "rewrite"

    # Max retries exceeded or unrecoverable error
    return "complete"


# =============================================================================
# Node Completion Checks
# =============================================================================


def is_retrieve_complete(state: RAGState) -> bool:
    """Check if retrieve node completed successfully."""
    return "retrieved_chunks" in state and state.get("error") is None


def is_rerank_complete(state: RAGState) -> bool:
    """Check if rerank node completed successfully."""
    return "reranked_chunks" in state and state.get("error") is None


def is_synthesize_complete(state: RAGState) -> bool:
    """Check if synthesize node completed successfully."""
    return "answer" in state and state.get("answer") and state.get("error") is None


def is_verify_complete(state: RAGState) -> bool:
    """Check if verify node completed successfully."""
    return "verification" in state and state.get("verification") is not None and state.get("error") is None


def is_guardrail_complete(state: RAGState) -> bool:
    """Check if guardrail node completed successfully."""
    return "guardrail_action" in state and state.get("error") is None


def is_hitl_complete(state: RAGState) -> bool:
    """Check if HITL node completed (either skipped or resumed)."""
    hitl_required = state.get("hitl_required", False)
    hitl_response = state.get("hitl_response")

    if not hitl_required:
        return True

    return hitl_response is not None


# =============================================================================
# Edge Configuration for StateGraph
# =============================================================================

# Mapping of node names to their conditional edge functions
CONDITIONAL_EDGES = {
    "verify": should_rewrite,           # verify -> rewrite OR retrieve
    "guardrail": should_hitl,           # guardrail -> hitl OR complete OR rewrite
    "hitl": should_continue_after_hitl, # hitl -> rewrite OR complete
}

# Terminal nodes
TERMINAL_NODES = ["complete"]

# Entry point
ENTRY_POINT = "rewrite"

# Node order for linear flow (before conditionals)
NODE_SEQUENCE = [
    "rewrite",
    "retrieve",
    "rerank",
    "synthesize",
    "verify",
    "guardrail",
    "hitl",
]
