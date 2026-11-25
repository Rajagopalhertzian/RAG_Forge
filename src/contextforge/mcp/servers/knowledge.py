"""
Knowledge MCP Server

Provides tools and resources for searching and retrieving documents from the knowledge base.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from contextforge.config import get_settings
from contextforge.mcp.schema import (
    KNOWLEDGE_RESOURCES,
    KNOWLEDGE_TOOLS,
    ListResourcesResult,
    ListToolsResult,
    ResourceReadParams,
    ResourceReadResult,
    ToolCallParams,
    ToolCallResult,
    validate_tool_call,
)
from contextforge.storage.database import get_db_session
from contextforge.storage.repositories.chunk import ChunkRepository
from contextforge.storage.repositories.document import DocumentRepository

# Import vector search - will be implemented based on actual vector store
try:
    from contextforge.vector_stores import get_vector_store
except ImportError:
    get_vector_store = None


class SearchResult(BaseModel):
    """Search result item."""

    doc_id: str
    title: str
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_ids: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Search tool response."""

    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0
    query: str = ""
    took_ms: float = 0


class DocumentResponse(BaseModel):
    """Get document tool response."""

    doc_id: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CollectionInfo(BaseModel):
    """Collection information."""

    name: str
    description: str
    document_count: int
    created_at: datetime


class CollectionsResponse(BaseModel):
    """List collections tool response."""

    collections: list[CollectionInfo] = Field(default_factory=list)


class KnowledgeServer:
    """
    Knowledge MCP Server.

    Provides tools for searching and retrieving documents from the knowledge base.
    Stateless worker - all state managed by gateway.
    """

    def __init__(self):
        self.settings = get_settings()
        self._vector_store = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize server connections."""
        if self._initialized:
            return

        # Initialize vector store
        if get_vector_store:
            self._vector_store = await get_vector_store()

        self._initialized = True

    async def close(self) -> None:
        """Close server connections."""
        self._initialized = False

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def search(
        self,
        query: str,
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        """
        Search the knowledge base for relevant documents.

        Args:
            query: Search query text
            k: Number of results to return (1-100)
            filters: Optional metadata filters

        Returns:
            SearchResponse with results and metadata
        """
        start_time = time.time()

        if not self._initialized:
            await self.initialize()

        # Validate inputs
        if not query or not query.strip():
            return SearchResponse(results=[], total=0, query=query, took_ms=0)

        k = max(1, min(k, 100))

        try:
            if self._vector_store:
                # Use vector store for semantic search
                results = await self._vector_store.search(
                    query=query,
                    k=k,
                    filters=filters or {},
                )

                search_results = [
                    SearchResult(
                        doc_id=r.get("doc_id", ""),
                        title=r.get("title", ""),
                        content=r.get("content", "")[:500],  # Truncate for response
                        score=r.get("score", 0.0),
                        metadata=r.get("metadata", {}),
                        chunk_ids=r.get("chunk_ids", []),
                    )
                    for r in results
                ]

                took_ms = (time.time() - start_time) * 1000
                return SearchResponse(
                    results=search_results,
                    total=len(search_results),
                    query=query,
                    took_ms=took_ms,
                )
            else:
                # Fallback to database text search
                return await self._fallback_search(query, k, filters)
        except Exception:
            # Return error as empty result with error info
            took_ms = (time.time() - start_time) * 1000
            return SearchResponse(
                results=[],
                total=0,
                query=query,
                took_ms=took_ms,
            )

    async def _fallback_search(
        self,
        query: str,
        k: int,
        filters: dict[str, Any] | None,
    ) -> SearchResponse:
        """Fallback text search using database."""
        start_time = time.time()

        try:
            async with get_db_session() as session:
                doc_repo = DocumentRepository(session)
                chunk_repo = ChunkRepository(session)

                # Search chunks by text (simple ILIKE for now)
                chunks = await chunk_repo.search_by_text(query, limit=k)

                # Group by document
                doc_map: dict[str, dict[str, Any]] = {}
                for chunk in chunks:
                    doc_id = chunk.document_id
                    if doc_id not in doc_map:
                        doc = await doc_repo.get_by_id(doc_id)
                        if doc:
                            doc_map[doc_id] = {
                                "doc_id": doc_id,
                                "title": doc.title,
                                "content": doc.content[:500] if doc.content else "",
                                "metadata": doc.metadata or {},
                                "chunks": [],
                                "score": 0.0,
                            }
                    doc_map[doc_id]["chunks"].append({
                        "chunk_id": chunk.id,
                        "content": chunk.content[:200],
                        "metadata": chunk.metadata or {},
                    })

                results = [
                    SearchResult(
                        doc_id=v["doc_id"],
                        title=v["title"],
                        content=v["content"],
                        score=v["score"],
                        metadata=v["metadata"],
                        chunk_ids=[c["chunk_id"] for c in v["chunks"]],
                    )
                    for v in doc_map.values()
                ]

                took_ms = (time.time() - start_time) * 1000
                return SearchResponse(
                    results=results[:k],
                    total=len(results),
                    query=query,
                    took_ms=took_ms,
                )
        except Exception:
            took_ms = (time.time() - start_time) * 1000
            return SearchResponse(results=[], total=0, query=query, took_ms=took_ms)

    async def get_document(self, doc_id: str) -> DocumentResponse | dict[str, Any]:
        """
        Retrieve a full document by ID.

        Args:
            doc_id: Document ID

        Returns:
            DocumentResponse with full document content
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with get_db_session() as session:
                doc_repo = DocumentRepository(session)
                chunk_repo = ChunkRepository(session)

                doc = await doc_repo.get_by_id(doc_id)
                if not doc:
                    return {"error": "Document not found", "doc_id": doc_id}

                chunks = await chunk_repo.get_by_document_id(doc_id)

                return DocumentResponse(
                    doc_id=doc.id,
                    title=doc.title,
                    content=doc.content or "",
                    metadata=doc.metadata or {},
                    chunks=[
                        {
                            "chunk_id": c.id,
                            "content": c.content,
                            "index": c.chunk_index,
                            "metadata": c.metadata or {},
                        }
                        for c in chunks
                    ],
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                )
        except Exception as e:
            return {"error": str(e), "doc_id": doc_id}

    async def list_collections(self) -> CollectionsResponse:
        """
        List all available document collections.

        Returns:
            CollectionsResponse with collection information
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with get_db_session() as session:
                doc_repo = DocumentRepository(session)

                # Get distinct collections from document metadata
                collections = await doc_repo.get_collections()

                return CollectionsResponse(
                    collections=[
                        CollectionInfo(
                            name=c["name"],
                            description=c.get("description", ""),
                            document_count=c["count"],
                            created_at=c["created_at"],
                        )
                        for c in collections
                    ]
                )
        except Exception:
            # Return default collection if DB fails
            return CollectionsResponse(
                collections=[
                    CollectionInfo(
                        name="default",
                        description="Default document collection",
                        document_count=0,
                        created_at=datetime.utcnow(),
                    )
                ]
            )

    # =========================================================================
    # Resource Implementations
    # =========================================================================

    async def read_document_resource(self, doc_id: str) -> ResourceReadResult:
        """Read document resource."""
        doc = await self.get_document(doc_id)
        if isinstance(doc, DocumentResponse):
            return ResourceReadResult(
                contents=[
                    {
                        "uri": f"document://{doc_id}",
                        "mimeType": "application/json",
                        "text": doc.model_dump_json(),
                    }
                ]
            )
        else:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": f"document://{doc_id}",
                        "mimeType": "application/json",
                        "text": json.dumps(doc),
                    }
                ]
            )

    async def read_collection_resource(self, name: str) -> ResourceReadResult:
        """Read collection resource."""
        collections = await self.list_collections()
        collection = next((c for c in collections.collections if c.name == name), None)

        if collection:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": f"collection://{name}",
                        "mimeType": "application/json",
                        "text": collection.model_dump_json(),
                    }
                ]
            )
        else:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": f"collection://{name}",
                        "mimeType": "application/json",
                        "text": json.dumps({"error": "Collection not found", "name": name}),
                    }
                ]
            )

    # =========================================================================
    # MCP Protocol Handlers
    # =========================================================================

    async def handle_tool_call(self, params: ToolCallParams) -> ToolCallResult:
        """Handle tool call from MCP protocol."""
        # Validate tool call
        valid, error = validate_tool_call(params.name, params.arguments)
        if not valid:
            return ToolCallResult(
                content=[{"type": "text", "text": error or "Invalid tool call"}],
                isError=True,
            )

        try:
            if params.name == "search":
                result = await self.search(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            elif params.name == "get_document":
                result = await self.get_document(**params.arguments)
                if isinstance(result, DocumentResponse):
                    return ToolCallResult(
                        content=[{"type": "text", "text": result.model_dump_json()}],
                        structuredContent=result.model_dump(),
                    )
                else:
                    return ToolCallResult(
                        content=[{"type": "text", "text": json.dumps(result)}],
                        isError="error" in result,
                    )
            elif params.name == "list_collections":
                result = await self.list_collections()
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            else:
                return ToolCallResult(
                    content=[{"type": "text", "text": f"Unknown tool: {params.name}"}],
                    isError=True,
                )
        except Exception as e:
            return ToolCallResult(
                content=[{"type": "text", "text": f"Tool execution error: {str(e)}"}],
                isError=True,
            )

    async def handle_resource_read(self, params: ResourceReadParams) -> ResourceReadResult:
        """Handle resource read from MCP protocol."""
        uri = params.uri

        if uri.startswith("document://"):
            doc_id = uri[len("document://"):]
            return await self.read_document_resource(doc_id)
        elif uri.startswith("collection://"):
            name = uri[len("collection://"):]
            return await self.read_collection_resource(name)
        else:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"error": f"Unknown resource URI: {uri}"}),
                    }
                ]
            )

    def get_tools(self) -> ListToolsResult:
        """Get list of available tools."""
        return ListToolsResult(tools=KNOWLEDGE_TOOLS)

    def get_resources(self) -> ListResourcesResult:
        """Get list of available resources."""
        return ListResourcesResult(resources=KNOWLEDGE_RESOURCES)


# Import json for error responses
import json

# Global server instance
_knowledge_server: KnowledgeServer | None = None


async def get_knowledge_server() -> KnowledgeServer:
    """Get or create knowledge server instance."""
    global _knowledge_server
    if _knowledge_server is None:
        _knowledge_server = KnowledgeServer()
        await _knowledge_server.initialize()
    return _knowledge_server


async def close_knowledge_server() -> None:
    """Close knowledge server instance."""
    global _knowledge_server
    if _knowledge_server:
        await _knowledge_server.close()
        _knowledge_server = None
