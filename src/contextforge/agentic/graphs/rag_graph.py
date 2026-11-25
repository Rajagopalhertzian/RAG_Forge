"""
ContextForge Agentic RAG Graph - Main StateGraph

LangGraph StateGraph with 7 nodes and conditional edges:
rewrite → retrieve → rerank → synthesize → verify → guardrail → hitl (conditional)

Features:
- Postgres checkpointer for persistence and HITL resume
- Streaming support via astream_events
- Configurable node models and parameters
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph

from contextforge.agentic.checkpointer import get_checkpointer
from contextforge.agentic.graphs.edges import (
    ENTRY_POINT,
    should_continue_after_hitl,
    should_hitl,
    should_rewrite,
)
from contextforge.agentic.nodes.guardrail import guardrail_node
from contextforge.agentic.nodes.hitl import hitl_node
from contextforge.agentic.nodes.rerank import rerank_node
from contextforge.agentic.nodes.retrieve import retrieve_node
from contextforge.agentic.nodes.rewrite import rewrite_node
from contextforge.agentic.nodes.synthesize import synthesize_node
from contextforge.agentic.nodes.verify import verify_node
from contextforge.agentic.state import RAGState, create_initial_state
from contextforge.main import logger

# =============================================================================
# Graph Construction
# =============================================================================


def create_rag_graph(checkpointer: PostgresSaver | MemorySaver | None = None) -> StateGraph:
    """
    Create the agentic RAG StateGraph.

    Args:
        checkpointer: Optional checkpointer (PostgresSaver for prod, MemorySaver for dev)
                     If None, creates appropriate checkpointer based on settings.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    # Use provided checkpointer or create default
    if checkpointer is None:
        checkpointer = get_checkpointer()

    # Initialize graph with state schema
    graph = StateGraph(RAGState)

    # Add all nodes
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("verify", verify_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("hitl", hitl_node)

    # Set entry point
    graph.set_entry_point(ENTRY_POINT)

    # Add linear edges
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "synthesize")
    graph.add_edge("synthesize", "verify")

    # Add conditional edges
    graph.add_conditional_edges(
        "verify",
        should_rewrite,
        {
            "rewrite": "rewrite",
            "retrieve": "retrieve",
        },
    )

    graph.add_conditional_edges(
        "guardrail",
        should_hitl,
        {
            "hitl": "hitl",
            "complete": END,
            "rewrite": "rewrite",
        },
    )

    graph.add_conditional_edges(
        "hitl",
        should_continue_after_hitl,
        {
            "rewrite": "rewrite",
            "complete": END,
        },
    )

    # Compile with checkpointer
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl"],  # Pause before HITL for human review
    )

    logger.info("rag_graph_compiled", checkpointer_type=type(checkpointer).__name__)

    return compiled


# =============================================================================
# Graph Invocation Helpers
# =============================================================================


class RAGGraphRunner:
    """High-level runner for the RAG graph with streaming and checkpoint support."""

    def __init__(self, graph: StateGraph | None = None):
        self.graph = graph or create_rag_graph()

    async def invoke(
        self,
        query: str,
        session_id: str | None = None,
        user_id: str | None = None,
        thread_id: str | None = None,
        top_k: int = 10,
        retrieval_k: int = 100,
        filters: dict[str, Any] | None = None,
        max_rewrites: int = 3,
        config: dict[str, Any] | None = None,
    ) -> RAGState:
        """
        Invoke the graph synchronously (waits for completion).

        Args:
            query: User query
            session_id: Session identifier
            user_id: User identifier
            thread_id: Thread ID for checkpointing (auto-generated if not provided)
            top_k: Final results to return
            retrieval_k: Initial retrieval pool size
            filters: Metadata filters
            max_rewrites: Maximum rewrite attempts
            config: Additional LangGraph config

        Returns:
            Final state after graph completion
        """
        import uuid

        thread_id = thread_id or f"rag_{uuid.uuid4().hex[:12]}"

        initial_state = create_initial_state(
            query=query,
            session_id=session_id,
            user_id=user_id,
            top_k=top_k,
            retrieval_k=retrieval_k,
            filters=filters,
            max_rewrites=max_rewrites,
        )

        run_config = {
            "configurable": {"thread_id": thread_id},
            **(config or {}),
        }

        logger.info(
            "graph_invoke_started",
            thread_id=thread_id,
            query=query[:100],
            request_id=initial_state["request_id"],
        )

        try:
            result = await self.graph.ainvoke(initial_state, config=run_config)
            logger.info(
                "graph_invoke_completed",
                thread_id=thread_id,
                request_id=result.get("request_id"),
                total_latency_ms=result.get("total_latency_ms"),
            )
            return result
        except Exception as e:
            logger.exception(
                "graph_invoke_failed",
                thread_id=thread_id,
                error=str(e),
            )
            raise

    async def stream(
        self,
        query: str,
        session_id: str | None = None,
        user_id: str | None = None,
        thread_id: str | None = None,
        top_k: int = 10,
        retrieval_k: int = 100,
        filters: dict[str, Any] | None = None,
        max_rewrites: int = 3,
        config: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Stream graph execution events.

        Yields:
            Events with type, phase, data for real-time UI updates
        """
        import uuid

        thread_id = thread_id or f"rag_{uuid.uuid4().hex[:12]}"

        initial_state = create_initial_state(
            query=query,
            session_id=session_id,
            user_id=user_id,
            top_k=top_k,
            retrieval_k=retrieval_k,
            filters=filters,
            max_rewrites=max_rewrites,
        )

        run_config = {
            "configurable": {"thread_id": thread_id},
            **(config or {}),
        }

        logger.info(
            "graph_stream_started",
            thread_id=thread_id,
            query=query[:100],
            request_id=initial_state["request_id"],
        )

        try:
            async for event in self.graph.astream_events(
                initial_state,
                config=run_config,
                version="v2",
            ):
                yield self._format_stream_event(event)
        except Exception as e:
            logger.exception("graph_stream_failed", thread_id=thread_id, error=str(e))
            yield {"type": "error", "error": str(e), "thread_id": thread_id}

    def _format_stream_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Format LangGraph stream event for API consumption."""
        event_type = event.get("event", "unknown")

        if event_type == "on_chain_start":
            return {
                "type": "phase_start",
                "phase": event["name"],
                "data": event.get("data", {}),
            }

        elif event_type == "on_chain_end":
            return {
                "type": "phase_complete",
                "phase": event["name"],
                "data": event.get("data", {}),
            }

        elif event_type == "on_chain_error":
            return {
                "type": "phase_error",
                "phase": event["name"],
                "error": str(event.get("data", {}).get("error", "Unknown error")),
            }

        elif event_type == "on_tool_start":
            return {
                "type": "tool_start",
                "tool": event["name"],
                "data": event.get("data", {}),
            }

        elif event_type == "on_tool_end":
            return {
                "type": "tool_complete",
                "tool": event["name"],
                "data": event.get("data", {}),
            }

        elif event_type == "on_chat_model_stream":
            # Token streaming from synthesis
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                return {
                    "type": "token",
                    "token": chunk.content,
                    "phase": "synthesize",
                }

        elif event_type == "interrupt":
            # HITL interrupt
            interrupt_data = event.get("data", {})
            return {
                "type": "interrupt",
                "interrupt_type": interrupt_data.get("type", "hitl_required"),
                "data": interrupt_data,
            }

        return {"type": "raw", "event": event}

    async def resume_from_hitl(
        self,
        thread_id: str,
        hitl_response: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> RAGState:
        """
        Resume graph after HITL with human response.

        Args:
            thread_id: Thread ID from original invocation
            hitl_response: Human reviewer response dict
            config: Additional LangGraph config

        Returns:
            Final state after resume
        """
        run_config = {
            "configurable": {"thread_id": thread_id},
            **(config or {}),
        }

        logger.info("graph_resume_from_hitl", thread_id=thread_id, action=hitl_response.get("action"))

        # Resume with HITL response
        # The interrupt value is passed via Command
        from langgraph.types import Command

        result = await self.graph.ainvoke(
            Command(resume=hitl_response),
            config=run_config,
        )

        return result

    async def get_state(self, thread_id: str) -> RAGState | None:
        """Get current graph state for a thread."""
        try:
            state = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
            return state.values if state else None
        except Exception as e:
            logger.warning("get_state_failed", thread_id=thread_id, error=str(e))
            return None


# =============================================================================
# Singleton Instance
# =============================================================================

_rag_graph: StateGraph | None = None
_rag_runner: RAGGraphRunner | None = None


def get_rag_graph() -> StateGraph:
    """Get or create singleton RAG graph."""
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = create_rag_graph()
    return _rag_graph


def get_rag_runner() -> RAGGraphRunner:
    """Get or create singleton RAG graph runner."""
    global _rag_runner
    if _rag_runner is None:
        _rag_runner = RAGGraphRunner(get_rag_graph())
    return _rag_runner


# =============================================================================
# Visualization (for debugging)
# =============================================================================

def visualize_graph(graph: StateGraph | None = None) -> str:
    """Generate Mermaid diagram of the graph."""
    g = graph or get_rag_graph()
    return g.get_graph().draw_mermaid()


if __name__ == "__main__":
    # Quick test
    import asyncio

    async def test():
        runner = get_rag_runner()
        result = await runner.invoke(
            query="How do I configure pgvector HNSW index?",
            session_id="test_session",
            user_id="test_user",
        )
        print(f"Answer: {result.get('answer', 'No answer')[:200]}...")
        print(f"Citations: {len(result.get('citations', []))}")
        print(f"Total latency: {result.get('total_latency_ms')}ms")

    asyncio.run(test())
