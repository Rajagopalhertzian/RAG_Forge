"""
MCP Schema Definitions

Pydantic models for MCP tool/resource schemas, message formats, and versioning.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SchemaVersion(str, Enum):
    """MCP schema versions for backward compatibility."""

    V1_0 = "1.0"
    V1_1 = "1.1"
    V2024_11_05 = "2024-11-05"  # Current MCP spec version
    V2025_06_18 = "2025-06-18"  # Updated spec with Streamable HTTP

    @classmethod
    def latest(cls) -> SchemaVersion:
        return cls.V2025_06_18

    @classmethod
    def default(cls) -> SchemaVersion:
        return cls.V2024_11_05


class ToolInputSchema(BaseModel):
    """JSON Schema for tool input validation."""

    type: Literal["object"] = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additionalProperties: bool = False


class ToolOutputSchema(BaseModel):
    """JSON Schema for tool output validation."""

    type: Literal["object"] = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolSchema(BaseModel):
    """MCP Tool schema with versioning and validation."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: str = Field(..., min_length=1, max_length=1000)
    inputSchema: ToolInputSchema
    outputSchema: ToolOutputSchema | None = None
    version: SchemaVersion = Field(default_factory=SchemaVersion.default)
    deprecated: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or v.startswith("_"):
            raise ValueError("Tool name must not be empty or start with underscore")
        return v


class ResourceSchema(BaseModel):
    """MCP Resource schema with versioning."""

    uri: str = Field(..., min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9+.-]*://.+")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=1000)
    mimeType: str = Field(default="application/json")
    version: SchemaVersion = Field(default_factory=SchemaVersion.default)
    deprecated: bool = False


class MCPError(BaseModel):
    """MCP error object per JSON-RPC 2.0 spec."""

    code: int = Field(..., ge=-32768, le=32767)
    message: str = Field(..., min_length=1)
    data: Any = None


class MCPRequest(BaseModel):
    """MCP request message (JSON-RPC 2.0 compatible)."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str = Field(..., min_length=1)
    params: dict[str, Any] | list[Any] | None = None
    version: SchemaVersion = Field(default_factory=SchemaVersion.default)

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        valid_methods = {
            "initialize",
            "initialized",
            "tools/list",
            "tools/call",
            "resources/list",
            "resources/read",
            "resources/subscribe",
            "resources/unsubscribe",
            "prompts/list",
            "prompts/get",
            "completion/complete",
            "logging/setLevel",
            "ping",
        }
        if v not in valid_methods and not v.startswith("notifications/"):
            raise ValueError(f"Invalid MCP method: {v}")
        return v


class MCPResponse(BaseModel):
    """MCP response message (JSON-RPC 2.0 compatible)."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any = None
    error: MCPError | None = None
    version: SchemaVersion = Field(default_factory=SchemaVersion.default)

    @model_validator(mode="after")
    def validate_exclusive_result_error(self) -> MCPResponse:
        if self.result is not None and self.error is not None:
            raise ValueError("Response cannot have both result and error")
        if self.result is None and self.error is None:
            raise ValueError("Response must have either result or error")
        return self


class MCPMessage(BaseModel):
    """Union type for MCP messages (request, response, notification)."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str | None = None
    params: dict[str, Any] | list[Any] | None = None
    result: Any = None
    error: MCPError | None = None
    version: SchemaVersion = Field(default_factory=SchemaVersion.default)

    def is_request(self) -> bool:
        return self.method is not None and self.id is not None

    def is_notification(self) -> bool:
        return self.method is not None and self.id is None

    def is_response(self) -> bool:
        return self.id is not None and self.method is None


class InitializeParams(BaseModel):
    """Initialize request parameters."""

    protocolVersion: SchemaVersion = Field(default_factory=SchemaVersion.default)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    clientInfo: dict[str, str] = Field(default_factory=dict)


class InitializeResult(BaseModel):
    """Initialize response result."""

    protocolVersion: SchemaVersion = Field(default_factory=SchemaVersion.default)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    serverInfo: dict[str, str] = Field(default_factory=dict)
    instructions: str | None = None


class ToolCallParams(BaseModel):
    """Tool call request parameters."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requestId: str | None = None


class ToolCallResult(BaseModel):
    """Tool call response result."""

    content: list[dict[str, Any]] = Field(default_factory=list)
    structuredContent: dict[str, Any] | None = None
    isError: bool = False


class ResourceReadParams(BaseModel):
    """Resource read request parameters."""

    uri: str


class ResourceReadResult(BaseModel):
    """Resource read response result."""

    contents: list[dict[str, Any]] = Field(default_factory=list)


class ListToolsResult(BaseModel):
    """List tools response result."""

    tools: list[ToolSchema] = Field(default_factory=list)
    nextCursor: str | None = None


class ListResourcesResult(BaseModel):
    """List resources response result."""

    resources: list[ResourceSchema] = Field(default_factory=list)
    nextCursor: str | None = None


# Tool schema definitions for each server
KNOWLEDGE_TOOLS: list[ToolSchema] = [
    ToolSchema(
        name="search",
        description="Search the knowledge base for relevant documents",
        inputSchema=ToolInputSchema(
            properties={
                "query": {"type": "string", "description": "Search query text"},
                "k": {"type": "integer", "description": "Number of results to return", "default": 10, "minimum": 1, "maximum": 100},
                "filters": {"type": "object", "description": "Optional metadata filters", "additionalProperties": True},
            },
            required=["query"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "string"},
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "score": {"type": "number"},
                            "metadata": {"type": "object"},
                        },
                    },
                },
                "total": {"type": "integer"},
            },
        ),
        tags=["knowledge", "search"],
    ),
    ToolSchema(
        name="get_document",
        description="Retrieve a full document by ID",
        inputSchema=ToolInputSchema(
            properties={
                "doc_id": {"type": "string", "description": "Document ID"},
            },
            required=["doc_id"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "doc_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "metadata": {"type": "object"},
                "chunks": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
        ),
        tags=["knowledge", "document"],
    ),
    ToolSchema(
        name="list_collections",
        description="List all available document collections",
        inputSchema=ToolInputSchema(properties={}),
        outputSchema=ToolOutputSchema(
            properties={
                "collections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "document_count": {"type": "integer"},
                            "created_at": {"type": "string", "format": "date-time"},
                        },
                    },
                },
            },
        ),
        tags=["knowledge", "collections"],
    ),
]

INGESTION_TOOLS: list[ToolSchema] = [
    ToolSchema(
        name="ingest_url",
        description="Ingest content from a URL",
        inputSchema=ToolInputSchema(
            properties={
                "url": {"type": "string", "format": "uri", "description": "URL to ingest"},
                "collection": {"type": "string", "description": "Target collection name", "default": "default"},
                "metadata": {"type": "object", "description": "Optional metadata to attach", "additionalProperties": True},
            },
            required=["url"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "job_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"]},
                "message": {"type": "string"},
            },
        ),
        tags=["ingestion", "url"],
    ),
    ToolSchema(
        name="ingest_file",
        description="Ingest content from a local file",
        inputSchema=ToolInputSchema(
            properties={
                "path": {"type": "string", "description": "File path to ingest"},
                "collection": {"type": "string", "description": "Target collection name", "default": "default"},
                "metadata": {"type": "object", "description": "Optional metadata to attach", "additionalProperties": True},
            },
            required=["path"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "job_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"]},
                "message": {"type": "string"},
            },
        ),
        tags=["ingestion", "file"],
    ),
    ToolSchema(
        name="ingest_status",
        description="Check the status of an ingestion job",
        inputSchema=ToolInputSchema(
            properties={
                "job_id": {"type": "string", "description": "Ingestion job ID"},
            },
            required=["job_id"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "job_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"]},
                "progress": {"type": "number", "minimum": 0, "maximum": 100},
                "documents_processed": {"type": "integer"},
                "chunks_created": {"type": "integer"},
                "error": {"type": "string"},
                "started_at": {"type": "string", "format": "date-time"},
                "completed_at": {"type": "string", "format": "date-time"},
            },
        ),
        tags=["ingestion", "status"],
    ),
]

ADMIN_TOOLS: list[ToolSchema] = [
    ToolSchema(
        name="get_metrics",
        description="Get system metrics and health information",
        inputSchema=ToolInputSchema(
            properties={
                "include_details": {"type": "boolean", "description": "Include detailed metrics", "default": False},
            },
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "status": {"type": "string"},
                "uptime_seconds": {"type": "number"},
                "requests_total": {"type": "integer"},
                "requests_per_minute": {"type": "number"},
                "error_rate": {"type": "number"},
                "active_connections": {"type": "integer"},
                "memory_usage_mb": {"type": "number"},
                "cpu_usage_percent": {"type": "number"},
                "database": {"type": "object"},
                "redis": {"type": "object"},
                "vector_store": {"type": "object"},
            },
        ),
        tags=["admin", "metrics"],
    ),
    ToolSchema(
        name="update_config",
        description="Update a configuration value",
        inputSchema=ToolInputSchema(
            properties={
                "key": {"type": "string", "description": "Configuration key"},
                "value": {"type": "string", "description": "Configuration value"},
                "persist": {"type": "boolean", "description": "Persist to config store", "default": False},
            },
            required=["key", "value"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "key": {"type": "string"},
                "value": {"type": "string"},
                "previous_value": {"type": "string"},
                "persisted": {"type": "boolean"},
            },
        ),
        tags=["admin", "config"],
    ),
    ToolSchema(
        name="trigger_eval",
        description="Trigger a retrieval evaluation run",
        inputSchema=ToolInputSchema(
            properties={
                "dataset": {"type": "string", "description": "Evaluation dataset name", "enum": ["v1_baseline", "v2_expanded"]},
                "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metrics to compute"},
                "config": {"type": "object", "description": "Evaluation configuration", "additionalProperties": True},
            },
            required=["dataset"],
        ),
        outputSchema=ToolOutputSchema(
            properties={
                "run_id": {"type": "string"},
                "status": {"type": "string"},
                "message": {"type": "string"},
            },
        ),
        tags=["admin", "evaluation"],
    ),
]

KNOWLEDGE_RESOURCES: list[ResourceSchema] = [
    ResourceSchema(
        uri="document://{id}",
        name="Document",
        description="Access a document by ID",
        mimeType="application/json",
    ),
    ResourceSchema(
        uri="collection://{name}",
        name="Collection",
        description="Access a collection by name",
        mimeType="application/json",
    ),
]

INGESTION_RESOURCES: list[ResourceSchema] = [
    ResourceSchema(
        uri="job://{id}",
        name="Ingestion Job",
        description="Access ingestion job status by ID",
        mimeType="application/json",
    ),
]

ADMIN_RESOURCES: list[ResourceSchema] = [
    ResourceSchema(
        uri="config://{key}",
        name="Configuration",
        description="Access configuration value by key",
        mimeType="application/json",
    ),
]

ALL_TOOLS = KNOWLEDGE_TOOLS + INGESTION_TOOLS + ADMIN_TOOLS
ALL_RESOURCES = KNOWLEDGE_RESOURCES + INGESTION_RESOURCES + ADMIN_RESOURCES


def get_tool_schema(name: str) -> ToolSchema | None:
    """Get tool schema by name."""
    for tool in ALL_TOOLS:
        if tool.name == name:
            return tool
    return None


def get_resource_schema(uri_pattern: str) -> ResourceSchema | None:
    """Get resource schema by URI pattern."""
    for resource in ALL_RESOURCES:
        if resource.uri == uri_pattern:
            return resource
    return None


def validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate tool call arguments against schema."""
    schema = get_tool_schema(tool_name)
    if not schema:
        return False, f"Unknown tool: {tool_name}"

    # Basic required field validation
    required = schema.inputSchema.required
    for field in required:
        if field not in arguments:
            return False, f"Missing required field: {field}"

    return True, None


def validate_resource_read(uri: str) -> tuple[bool, str | None]:
    """Validate resource URI against known patterns."""
    # Simple pattern matching for now
    known_patterns = [r.uri for r in ALL_RESOURCES]
    for pattern in known_patterns:
        # Convert pattern to regex
        import re
        regex = pattern.replace("{id}", r"[^/]+").replace("{name}", r"[^/]+").replace("{key}", r"[^/]+")
        if re.match(f"^{regex}$", uri):
            return True, None
    return False, f"Unknown resource URI pattern: {uri}"
