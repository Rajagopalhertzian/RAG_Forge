"""
ContextForge MCP (Model Context Protocol) Module

Provides MCP Gateway and specialized MCP servers for Knowledge, Ingestion, and Admin operations.
"""

from contextforge.mcp.auth import MCPAuth, OAuth21Provider
from contextforge.mcp.gateway import MCPGateway
from contextforge.mcp.schema import (
    MCPError,
    MCPMessage,
    MCPRequest,
    MCPResponse,
    ResourceSchema,
    SchemaVersion,
    ToolSchema,
)
from contextforge.mcp.transport import SSETransport, StreamableHTTPTransport

__all__ = [
    "MCPGateway",
    "MCPAuth",
    "OAuth21Provider",
    "SSETransport",
    "StreamableHTTPTransport",
    "ToolSchema",
    "ResourceSchema",
    "MCPMessage",
    "MCPRequest",
    "MCPResponse",
    "MCPError",
    "SchemaVersion",
]
