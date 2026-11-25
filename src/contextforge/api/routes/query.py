"""
ContextForge Query API Routes

POST /query - Execute agentic RAG query (sync)
POST /query/stream - Execute agentic RAG query (streaming SSE)
GET /query/hitl/{thread_id} - Get HITL status
POST /query/hitl/{thread_id}/respond - Submit HITL response
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from contextforge.agentic.graphs.rag_graph import get_rag_runner
from contextforge.agentic.streaming import create_streaming_response
from contextforge.agentic.tools.registry import tool_registry
from contextforge.main import logger

router = APIRouter(prefix="/api/v1/query", tags=["query"])


# =============================================================================
# Request/Response Models
# =============================================================================


class QueryRequest(BaseModel):
    """Request model for RAG query."""

    query: str = Field(..., description="User query", min_length=1, max_length=5000)
    session_id: str | None = Field(None, description="Session ID for conversation context")
    user_id: str | None = Field(None, description="User ID for personalization")
    top_k: int = Field(10, description="Final number of results", ge=1, le=50)
    retrieval_k: int = Field(100, description="Initial retrieval pool size", ge=10, le=500)
    filters: dict[str, Any] = Field(default_factory=dict, description="Metadata filters")
    max_rewrites: int = Field(3, description="Maximum rewrite attempts", ge=0, le=10)


class QueryResponse(BaseModel):
    """Response model for RAG query."""

    answer: str
    citations: list[dict[str, Any]]
    verification: dict[str, Any] | None
    guardrail_action: str
    hitl_required: bool
    latency_ms: int
    request_id: str
    thread_id: str


class StreamQueryRequest(QueryRequest):
    """Request model for streaming query (same as QueryRequest)."""
    pass


class HITLResponseRequest(BaseModel):
    """HITL response from human reviewer."""

    action: str = Field(..., description="Action: approve, reject, modify, escalate")
    modified_answer: str | None = Field(None, description="Modified answer if action=modify")
    reviewer_notes: str | None = Field(None, description="Reviewer notes")
    reviewer_id: str | None = Field(None, description="Reviewer identifier")


class HITLStatusResponse(BaseModel):
    """HITL status response."""

    thread_id: str
    hitl_required: bool
    checkpoint_id: str | None
    payload: dict[str, Any] | None
    status: str  # awaiting_review, completed, not_required


# =============================================================================
# Routes
# =============================================================================


@router.post("/query", response_model=QueryResponse)
async def query_rag(request: QueryRequest) -> QueryResponse:
    """
    Execute agentic RAG query synchronously.

    Runs the full 7-node graph: rewrite → retrieve → rerank → synthesize →
    verify → guardrail → hitl (conditional)

    Returns final answer with citations and verification metadata.
    """
    runner = get_rag_runner()

    try:
        result = await runner.invoke(
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            top_k=request.top_k,
            retrieval_k=request.retrieval_k,
            filters=request.filters,
            max_rewrites=request.max_rewrites,
        )

        return QueryResponse(
            answer=result.get("answer", ""),
            citations=[
                {
                    "claim": c.claim,
                    "chunk_ids": [str(cid) for cid in c.chunk_ids],
                    "chunk_scores": c.chunk_scores,
                }
                for c in result.get("citations", [])
            ],
            verification={
                "confidence": result.get("verification", {}).confidence if result.get("verification") else None,
                "factual_consistency": result.get("verification", {}).factual_consistency if result.get("verification") else None,
                "answer_completeness": result.get("verification", {}).answer_completeness if result.get("verification") else None,
                "hallucination_flags": result.get("verification", {}).hallucination_flags if result.get("verification") else [],
                "rewrite_signal": result.get("verification", {}).rewrite_signal if result.get("verification") else False,
            } if result.get("verification") else None,
            guardrail_action=result.get("guardrail_action", "proceed"),
            hitl_required=result.get("hitl_required", False),
            latency_ms=result.get("total_latency_ms", 0),
            request_id=result.get("request_id", ""),
            thread_id=result.get("graph_checkpoint_id", "").replace("hitl_", "") if result.get("graph_checkpoint_id") else "",
        )

    except Exception as e:
        logger.exception("query_rag_failed", error=str(e), query=request.query[:100])
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.post("/query/stream")
async def query_rag_stream(request: StreamQueryRequest) -> StreamingResponse:
    """
    Execute agentic RAG query with Server-Sent Events streaming.

    Streams events:
    - phase_start / phase_complete (rewrite, retrieve, rerank, synthesize, verify, guardrail, hitl)
    - token (during synthesis)
    - tool_start / tool_complete
    - interrupt (HITL required)
    - complete (final result)
    - error

    Client should parse SSE format: "data: {...}\n\n"
    """
    # Validate request
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        sse_response = await create_streaming_response(
            graph=None,  # Uses singleton
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            thread_id=None,  # Auto-generate
            top_k=request.top_k,
            retrieval_k=request.retrieval_k,
            filters=request.filters,
            max_rewrites=request.max_rewrites,
        )

        return StreamingResponse(
            sse_response,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    except Exception as e:
        logger.exception("query_rag_stream_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Streaming query failed: {str(e)}")


@router.get("/hitl/{thread_id}", response_model=HITLStatusResponse)
async def get_hitl_status(thread_id: str) -> HITLStatusResponse:
    """
    Get HITL status for a thread.

    Returns current state including HITL payload if awaiting review.
    """
    runner = get_rag_runner()

    try:
        state = await runner.get_state(thread_id)

        if not state:
            raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

        hitl_required = state.get("hitl_required", False)
        checkpoint_id = state.get("graph_checkpoint_id")
        payload = state.get("hitl_payload")

        return HITLStatusResponse(
            thread_id=thread_id,
            hitl_required=hitl_required,
            checkpoint_id=checkpoint_id,
            payload=payload,
            status="awaiting_review" if hitl_required and not state.get("hitl_response") else
                   "completed" if not hitl_required else "processing",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("hitl_status_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get HITL status: {str(e)}")


@router.post("/hitl/{thread_id}/respond")
async def submit_hitl_response(
    thread_id: str,
    response: HITLResponseRequest,
) -> QueryResponse:
    """
    Submit HITL response to resume a paused graph.

    Actions:
    - approve: Continue with original answer
    - modify: Use modified_answer as final answer
    - reject: Trigger rewrite loop
    - escalate: Block and flag for admin
    """
    runner = get_rag_runner()

    # Validate action
    valid_actions = ["approve", "reject", "modify", "escalate"]
    if response.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {response.action}. Must be one of: {valid_actions}",
        )

    if response.action == "modify" and not response.modified_answer:
        raise HTTPException(
            status_code=400,
            detail="modified_answer required when action=modify",
        )

    try:
        hitl_response = {
            "action": response.action,
            "modified_answer": response.modified_answer,
            "reviewer_notes": response.reviewer_notes,
            "reviewer_id": response.reviewer_id,
        }

        result = await runner.resume_from_hitl(thread_id, hitl_response)

        return QueryResponse(
            answer=result.get("answer", ""),
            citations=[
                {
                    "claim": c.claim,
                    "chunk_ids": [str(cid) for cid in c.chunk_ids],
                    "chunk_scores": c.chunk_scores,
                }
                for c in result.get("citations", [])
            ],
            verification={
                "confidence": result.get("verification", {}).confidence if result.get("verification") else None,
                "factual_consistency": result.get("verification", {}).factual_consistency if result.get("verification") else None,
                "answer_completeness": result.get("verification", {}).answer_completeness if result.get("verification") else None,
                "hallucination_flags": result.get("verification", {}).hallucination_flags if result.get("verification") else [],
            } if result.get("verification") else None,
            guardrail_action=result.get("guardrail_action", "proceed"),
            hitl_required=result.get("hitl_required", False),
            latency_ms=result.get("total_latency_ms", 0),
            request_id=result.get("request_id", ""),
            thread_id=thread_id,
        )

    except Exception as e:
        logger.exception("hitl_response_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"HITL response failed: {str(e)}")


@router.get("/tools")
async def list_tools(category: str | None = Query(None)) -> dict[str, Any]:
    """List available MCP-compatible tools."""
    schemas = tool_registry.list_tools(category)
    return {
        "tools": [s.model_dump() for s in schemas],
        "categories": tool_registry.list_categories(),
    }


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str) -> dict[str, Any]:
    """Get tool schema by name."""
    tool = tool_registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    return tool.schema.model_dump()


@router.post("/tools/{tool_name}/invoke")
async def invoke_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke a tool directly (for testing/MCP)."""
    tool = tool_registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")

    try:
        result = await tool.handler(**arguments)
        return {"result": result}
    except Exception as e:
        logger.exception("tool_invoke_failed", tool=tool_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Tool invocation failed: {str(e)}")


# =============================================================================
# Health Check for Query Service
# =============================================================================


@router.get("/health")
async def query_health() -> dict[str, Any]:
    """Health check for query service."""
    return {
        "status": "healthy",
        "service": "query",
        "graph_nodes": ["rewrite", "retrieve", "rerank", "synthesize", "verify", "guardrail", "hitl"],
        "tools_available": len(tool_registry.list_tools()),
    }
