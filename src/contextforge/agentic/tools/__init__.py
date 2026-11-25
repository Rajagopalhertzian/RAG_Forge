"""
ContextForge Agentic Tools

Tool registry and implementations.
"""

from __future__ import annotations

from contextforge.agentic.tools.registry import (
    DOCUMENT_GET_SCHEMA,
    DOCUMENT_LIST_SCHEMA,
    HYBRID_SEARCH_SCHEMA,
    RAG_QUERY_OUTPUT_SCHEMA,
    RAG_QUERY_SCHEMA,
    VECTOR_SEARCH_SCHEMA,
    Tool,
    ToolRegistry,
    ToolSchema,
    get_all_tool_schemas,
    get_tool_schemas_by_category,
    register_retrieval_tools,
    tool_registry,
)
from contextforge.agentic.tools.retriever import (
    DocumentTool,
    RAGQueryTool,
    RetrieverTool,
    create_tool_handlers,
)

__all__ = [
    # Registry
    "ToolRegistry",
    "ToolSchema",
    "Tool",
    "tool_registry",
    "register_retrieval_tools",
    "get_all_tool_schemas",
    "get_tool_schemas_by_category",
    # Schemas
    "VECTOR_SEARCH_SCHEMA",
    "HYBRID_SEARCH_SCHEMA",
    "DOCUMENT_GET_SCHEMA",
    "DOCUMENT_LIST_SCHEMA",
    "RAG_QUERY_SCHEMA",
    "RAG_QUERY_OUTPUT_SCHEMA",
    # Tools
    "RetrieverTool",
    "DocumentTool",
    "RAGQueryTool",
    "create_tool_handlers",
]
