"""
ContextForge Agentic RAG Module

Agentic RAG pipeline with LangGraph StateGraph.
"""

from __future__ import annotations

from contextforge.agentic.checkpointer import (
    checkpointer_manager,
    get_async_checkpointer,
    get_checkpointer,
)
from contextforge.agentic.graphs.rag_graph import RAGGraphRunner, create_rag_graph, get_rag_runner
from contextforge.agentic.state import RAGState, create_initial_state
from contextforge.agentic.streaming import (
    create_streaming_response,
    event_to_sse,
    stream_graph_events,
)

__all__ = [
    # State
    "RAGState",
    "create_initial_state",
    # Graph
    "create_rag_graph",
    "get_rag_runner",
    "RAGGraphRunner",
    # Checkpointer
    "get_checkpointer",
    "get_async_checkpointer",
    "checkpointer_manager",
    # Streaming
    "stream_graph_events",
    "create_streaming_response",
    "event_to_sse",
]

__version__ = "0.1.0"
