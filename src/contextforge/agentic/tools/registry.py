"""
ContextForge Tool Registry - MCP-compatible Tool Definitions

Provides tool registry with JSON Schema validation for:
- Vector search
- Hybrid search
- Document retrieval
- Graph invocation
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from contextforge.main import logger

# =============================================================================
# Tool Definitions
# =============================================================================


class ToolSchema(BaseModel):
    """Tool definition with JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    required: list[str] = Field(default_factory=list)
    returns: dict[str, Any] | None = None  # Output schema


class Tool(BaseModel):
    """Registered tool with schema and handler."""

    schema: ToolSchema
    handler: Callable[..., Any]
    category: str = "retrieval"


# =============================================================================
# Tool Registry
# =============================================================================


class ToolRegistry:
    """Registry for managing tools with schemas."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._categories: dict[str, list[str]] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        category: str = "retrieval",
        required: list[str] | None = None,
        returns: dict[str, Any] | None = None,
    ) -> Tool:
        """Register a new tool."""
        schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters,
            required=required or [],
            returns=returns,
        )

        tool = Tool(schema=schema, handler=handler, category=category)
        self._tools[name] = tool

        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(name)

        logger.info("tool_registered", name=name, category=category)
        return tool

    def get(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolSchema]:
        """List all tool schemas, optionally filtered by category."""
        tools = self._tools.values()
        if category:
            tools = [t for t in tools if t.category == category]
        return [t.schema for t in tools]

    def list_categories(self) -> list[str]:
        """List all categories."""
        return list(self._categories.keys())

    def get_category_tools(self, category: str) -> list[ToolSchema]:
        """Get all tools in a category."""
        return self.list_tools(category)

    def to_openai_functions(self, category: str | None = None) -> list[dict[str, Any]]:
        """Convert tools to OpenAI function calling format."""
        functions = []
        for tool in self._tools.values():
            if category and tool.category != category:
                continue
            functions.append({
                "type": "function",
                "function": {
                    "name": tool.schema.name,
                    "description": tool.schema.description,
                    "parameters": tool.schema.parameters,
                },
            })
        return functions

    def to_mcp_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """Convert tools to MCP tool format."""
        tools = []
        for tool in self._tools.values():
            if category and tool.category != category:
                continue
            tools.append({
                "name": tool.schema.name,
                "description": tool.schema.description,
                "inputSchema": tool.schema.parameters,
            })
        return tools


# =============================================================================
# Global Registry
# =============================================================================

tool_registry = ToolRegistry()


# =============================================================================
# Built-in Tool Schemas
# =============================================================================

VECTOR_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query text"},
        "top_k": {"type": "integer", "description": "Number of results", "default": 10, "minimum": 1, "maximum": 100},
        "filters": {"type": "object", "description": "Metadata filters", "default": {}},
        "score_threshold": {"type": "number", "description": "Minimum similarity score", "default": 0.0},
    },
    "required": ["query"],
}

HYBRID_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query text"},
        "top_k": {"type": "integer", "description": "Number of results", "default": 10, "minimum": 1, "maximum": 100},
        "filters": {"type": "object", "description": "Metadata filters", "default": {}},
        "vector_weight": {"type": "number", "description": "Vector search weight (0-1)", "default": 0.5},
        "bm25_weight": {"type": "number", "description": "BM25 search weight (0-1)", "default": 0.5},
    },
    "required": ["query"],
}

DOCUMENT_GET_SCHEMA = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string", "format": "uuid", "description": "Document UUID"},
        "include_chunks": {"type": "boolean", "description": "Include chunks in response", "default": False},
    },
    "required": ["document_id"],
}

DOCUMENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "source_type": {"type": "string", "description": "Filter by source type"},
        "limit": {"type": "integer", "description": "Max results", "default": 50, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
    },
}

RAG_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "User query"},
        "session_id": {"type": "string", "description": "Session ID for context"},
        "user_id": {"type": "string", "description": "User ID for personalization"},
        "top_k": {"type": "integer", "description": "Final results", "default": 10},
        "retrieval_k": {"type": "integer", "description": "Initial retrieval pool", "default": 100},
        "filters": {"type": "object", "description": "Metadata filters", "default": {}},
        "stream": {"type": "boolean", "description": "Stream response", "default": False},
    },
    "required": ["query"],
}

RAG_QUERY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "chunk_ids": {"type": "array", "items": {"type": "string"}},
                    "chunk_scores": {"type": "array", "items": {"type": "number"}},
                },
            },
        },
        "verification": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "factual_consistency": {"type": "number"},
                "answer_completeness": {"type": "number"},
            },
        },
        "latency_ms": {"type": "integer"},
    },
}


# =============================================================================
# Registration Helpers
# =============================================================================


def register_retrieval_tools(handlers: dict[str, Callable]) -> None:
    """Register all retrieval tools with handlers."""
    # Vector search
    tool_registry.register(
        name="vector_search",
        description="Search documents using vector similarity (pgvector HNSW)",
        parameters=VECTOR_SEARCH_SCHEMA,
        handler=handlers.get("vector_search"),
        category="retrieval",
        required=["query"],
        returns={"type": "object", "properties": {"results": {"type": "array"}}},
    )

    # Hybrid search
    tool_registry.register(
        name="hybrid_search",
        description="Hybrid search combining vector and BM25 with RRF fusion",
        parameters=HYBRID_SEARCH_SCHEMA,
        handler=handlers.get("hybrid_search"),
        category="retrieval",
        required=["query"],
        returns={"type": "object", "properties": {"results": {"type": "array"}}},
    )

    # Document get
    tool_registry.register(
        name="get_document",
        description="Get document by ID with optional chunks",
        parameters=DOCUMENT_GET_SCHEMA,
        handler=handlers.get("get_document"),
        category="document",
        required=["document_id"],
    )

    # Document list
    tool_registry.register(
        name="list_documents",
        description="List documents with pagination and filtering",
        parameters=DOCUMENT_LIST_SCHEMA,
        handler=handlers.get("list_documents"),
        category="document",
    )

    # RAG query (full graph)
    tool_registry.register(
        name="rag_query",
        description="Full agentic RAG query with rewrite, retrieve, rerank, synthesize, verify, guardrails",
        parameters=RAG_QUERY_SCHEMA,
        handler=handlers.get("rag_query"),
        category="rag",
        required=["query"],
        returns=RAG_QUERY_OUTPUT_SCHEMA,
    )


def get_all_tool_schemas() -> list[ToolSchema]:
    """Get all registered tool schemas."""
    return tool_registry.list_tools()


def get_tool_schemas_by_category(category: str) -> list[ToolSchema]:
    """Get tool schemas for a specific category."""
    return tool_registry.get_category_tools(category)
