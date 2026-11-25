"""
ContextForge Streaming - astream_events with Token/Tool/Phase Yields

Provides structured streaming events for real-time UI updates:
- Phase transitions (rewrite, retrieve, rerank, synthesize, verify, guardrail, hitl)
- Token streaming from synthesis
- Tool invocations
- Interrupts (HITL)
- Errors
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from contextforge.agentic.state import RAGState
from contextforge.main import logger

# =============================================================================
# Event Types
# =============================================================================


@dataclass
class StreamEvent:
    """Base streaming event."""

    type: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    request_id: str | None = None
    thread_id: str | None = None


@dataclass
class PhaseEvent(StreamEvent):
    """Phase transition event."""

    phase: str = ""
    status: str = "start"  # start, complete, error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenEvent(StreamEvent):
    """Token streaming event."""

    token: str = ""
    phase: str = "synthesize"
    accumulated: str = ""


@dataclass
class ToolEvent(StreamEvent):
    """Tool invocation event."""

    tool: str = ""
    status: str = "start"  # start, complete, error
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class InterruptEvent(StreamEvent):
    """HITL interrupt event."""

    interrupt_type: str = "hitl_required"
    checkpoint_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorEvent(StreamEvent):
    """Error event."""

    error: str = ""
    phase: str | None = None
    node: str | None = None
    recoverable: bool = True


@dataclass
class CompleteEvent(StreamEvent):
    """Graph completion event."""

    answer: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    total_latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Event Formatter
# =============================================================================


class StreamFormatter:
    """Formats LangGraph events into structured StreamEvents."""

    def __init__(self, request_id: str | None = None, thread_id: str | None = None):
        self.request_id = request_id
        self.thread_id = thread_id
        self.accumulated_answer = ""
        self.phase_start_times: dict[str, float] = {}

    def format(self, event: dict[str, Any]) -> StreamEvent | None:
        """Format raw LangGraph event to structured event."""
        event_type = event.get("event", "unknown")

        if event_type == "on_chain_start":
            return self._format_chain_start(event)
        elif event_type == "on_chain_end":
            return self._format_chain_end(event)
        elif event_type == "on_chain_error":
            return self._format_chain_error(event)
        elif event_type == "on_tool_start":
            return self._format_tool_start(event)
        elif event_type == "on_tool_end":
            return self._format_tool_end(event)
        elif event_type == "on_chat_model_stream":
            return self._format_token_stream(event)
        elif event_type == "interrupt":
            return self._format_interrupt(event)

        return None

    def _format_chain_start(self, event: dict[str, Any]) -> PhaseEvent:
        phase = event.get("name", "unknown")
        self.phase_start_times[phase] = time.perf_counter()

        return PhaseEvent(
            type="phase_start",
            phase=phase,
            status="start",
            data=event.get("data", {}),
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_chain_end(self, event: dict[str, Any]) -> PhaseEvent:
        phase = event.get("name", "unknown")
        start_time = self.phase_start_times.pop(phase, time.perf_counter())
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return PhaseEvent(
            type="phase_complete",
            phase=phase,
            status="complete",
            data={**event.get("data", {}), "latency_ms": latency_ms},
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_chain_error(self, event: dict[str, Any]) -> ErrorEvent:
        phase = event.get("name", "unknown")
        error_data = event.get("data", {})
        error_msg = str(error_data.get("error", "Unknown error"))

        return ErrorEvent(
            type="error",
            error=error_msg,
            phase=phase,
            node=phase,
            recoverable=True,
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_tool_start(self, event: dict[str, Any]) -> ToolEvent:
        return ToolEvent(
            type="tool_start",
            tool=event.get("name", "unknown"),
            status="start",
            input=event.get("data", {}).get("input", {}),
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_tool_end(self, event: dict[str, Any]) -> ToolEvent:
        return ToolEvent(
            type="tool_complete",
            tool=event.get("name", "unknown"),
            status="complete",
            output=event.get("data", {}).get("output", {}),
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_token_stream(self, event: dict[str, Any]) -> TokenEvent | None:
        chunk = event.get("data", {}).get("chunk")
        if not chunk:
            return None

        content = getattr(chunk, "content", "")
        if not content:
            return None

        self.accumulated_answer += content

        return TokenEvent(
            type="token",
            token=content,
            phase="synthesize",
            accumulated=self.accumulated_answer,
            request_id=self.request_id,
            thread_id=self.thread_id,
        )

    def _format_interrupt(self, event: dict[str, Any]) -> InterruptEvent:
        interrupt_data = event.get("data", {})

        return InterruptEvent(
            type="interrupt",
            interrupt_type=interrupt_data.get("type", "hitl_required"),
            checkpoint_id=interrupt_data.get("checkpoint_id", ""),
            payload=interrupt_data,
            request_id=self.request_id,
            thread_id=self.thread_id,
        )


# =============================================================================
# Streaming Helpers
# =============================================================================


async def stream_graph_events(
    graph: Any,
    initial_state: RAGState,
    config: dict[str, Any],
    request_id: str | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Stream events from graph execution.

    Yields structured StreamEvent objects for each phase/token/tool/interrupt.
    """
    formatter = StreamFormatter(request_id=request_id, thread_id=thread_id)

    try:
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            formatted = formatter.format(event)
            if formatted:
                yield formatted

        # Final completion event
        # Get final state
        final_state = await graph.aget_state(config)
        if final_state and final_state.values:
            state = final_state.values
            yield CompleteEvent(
                type="complete",
                answer=state.get("answer", ""),
                citations=[
                    {
                        "claim": c.claim,
                        "chunk_ids": [str(cid) for cid in c.chunk_ids],
                        "chunk_scores": c.chunk_scores,
                    }
                    for c in state.get("citations", [])
                ],
                total_latency_ms=state.get("total_latency_ms", 0),
                metadata={
                    "verification": {
                        "confidence": state.get("verification", {}).confidence if state.get("verification") else None,
                    },
                    "guardrail_action": state.get("guardrail_action"),
                    "hitl_required": state.get("hitl_required"),
                },
                request_id=request_id,
                thread_id=thread_id,
            )

    except Exception as e:
        logger.exception("stream_graph_events_failed", error=str(e))
        yield ErrorEvent(
            type="error",
            error=str(e),
            recoverable=False,
            request_id=request_id,
            thread_id=thread_id,
        )


def event_to_dict(event: StreamEvent) -> dict[str, Any]:
    """Convert StreamEvent to dict for JSON serialization."""
    return {
        "type": event.type,
        "timestamp": event.timestamp,
        "request_id": event.request_id,
        "thread_id": event.thread_id,
        **{k: v for k, v in event.__dict__.items()
           if k not in ("type", "timestamp", "request_id", "thread_id")},
    }


def event_to_sse(event: StreamEvent) -> str:
    """Convert StreamEvent to Server-Sent Events format."""
    data = json.dumps(event_to_dict(event), default=str)
    return f"data: {data}\n\n"


# =============================================================================
# SSE Response Helper (for FastAPI)
# =============================================================================


class SSEResponse:
    """Helper for creating SSE streaming responses."""

    def __init__(self, event_generator: AsyncGenerator[StreamEvent, None]):
        self.event_generator = event_generator

    async def __call__(self, send: Any) -> None:
        """ASGI send callable for StreamingResponse."""
        try:
            async for event in self.event_generator:
                sse_data = event_to_sse(event)
                await send({
                    "type": "http.response.body",
                    "body": sse_data.encode(),
                    "more_body": True,
                })
        except Exception as e:
            logger.exception("sse_response_error", error=str(e))
            error_event = ErrorEvent(type="error", error=str(e), recoverable=False)
            await send({
                "type": "http.response.body",
                "body": event_to_sse(error_event).encode(),
                "more_body": False,
            })
        finally:
            # Send final empty chunk to close
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            })


# =============================================================================
# Convenience Function for API Routes
# =============================================================================


async def create_streaming_response(
    graph: Any,
    query: str,
    session_id: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    top_k: int = 10,
    retrieval_k: int = 100,
    filters: dict[str, Any] | None = None,
    max_rewrites: int = 3,
) -> SSEResponse:
    """
    Create SSE response for streaming RAG query.

    Usage in FastAPI:
        return StreamingResponse(
            create_streaming_response(...),
            media_type="text/event-stream"
        )
    """
    from contextforge.agentic.graphs.rag_graph import get_rag_runner
    from contextforge.agentic.state import create_initial_state

    runner = get_rag_runner()

    import uuid
    request_id = str(uuid.uuid4())
    thread_id = thread_id or f"rag_{uuid.uuid4().hex[:12]}"

    initial_state = create_initial_state(
        query=query,
        session_id=session_id,
        user_id=user_id,
        top_k=top_k,
        retrieval_k=retrieval_k,
        filters=filters,
        max_rewrites=max_rewrites,
        request_id=request_id,
    )

    config = {"configurable": {"thread_id": thread_id}}

    event_gen = stream_graph_events(
        runner.graph,
        initial_state,
        config,
        request_id=request_id,
        thread_id=thread_id,
    )

    return SSEResponse(event_gen)
