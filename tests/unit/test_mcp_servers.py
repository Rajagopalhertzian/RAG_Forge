"""
Unit tests for MCP Servers.

Tests Knowledge, Ingestion, and Admin server implementations.
"""

from __future__ import annotations

import pytest

from contextforge.mcp.schema import (
    ADMIN_TOOLS,
    INGESTION_TOOLS,
    KNOWLEDGE_TOOLS,
    ListResourcesResult,
    ListToolsResult,
    ToolCallParams,
    validate_resource_read,
    validate_tool_call,
)


class TestKnowledgeServer:
    """Tests for Knowledge Server."""

    @pytest.fixture
    def mock_server(self):
        """Create a mocked knowledge server."""
        from contextforge.mcp.servers.knowledge import KnowledgeServer
        server = KnowledgeServer()
        server._initialized = True
        return server

    @pytest.mark.asyncio
    async def test_search_tool_exists(self):
        """Test that search tool is defined."""
        tool_names = [t.name for t in KNOWLEDGE_TOOLS]
        assert "search" in tool_names
        assert "get_document" in tool_names
        assert "list_collections" in tool_names

    @pytest.mark.asyncio
    async def test_search_tool_schema(self):
        """Test search tool schema validation."""
        search_tool = next(t for t in KNOWLEDGE_TOOLS if t.name == "search")
        assert search_tool.inputSchema.required == ["query"]
        assert "k" in search_tool.inputSchema.properties
        assert "filters" in search_tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_validate_search_tool_call(self):
        """Test search tool call validation."""
        valid, error = validate_tool_call("search", {"query": "test"})
        assert valid
        assert error is None

        valid, error = validate_tool_call("search", {})
        assert not valid
        assert "query" in error

    @pytest.mark.asyncio
    async def test_get_tools(self, mock_server):
        """Test get_tools returns correct tools."""
        result = mock_server.get_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 3
        tool_names = [t.name for t in result.tools]
        assert set(tool_names) == {"search", "get_document", "list_collections"}

    @pytest.mark.asyncio
    async def test_get_resources(self, mock_server):
        """Test get_resources returns correct resources."""
        result = mock_server.get_resources()
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 2
        uris = [r.uri for r in result.resources]
        assert "document://{id}" in uris
        assert "collection://{name}" in uris

    @pytest.mark.asyncio
    async def test_handle_unknown_tool(self, mock_server):
        """Test handling unknown tool."""
        params = ToolCallParams(name="unknown_tool", arguments={})
        result = await mock_server.handle_tool_call(params)
        assert result.isError
        assert "Unknown tool" in result.content[0]["text"]


class TestIngestionServer:
    """Tests for Ingestion Server."""

    @pytest.fixture
    def mock_server(self):
        """Create a mocked ingestion server."""
        from contextforge.mcp.servers.ingestion import IngestionServer
        server = IngestionServer()
        server._initialized = True
        return server

    @pytest.mark.asyncio
    async def test_ingestion_tools_exist(self):
        """Test that ingestion tools are defined."""
        tool_names = [t.name for t in INGESTION_TOOLS]
        assert "ingest_url" in tool_names
        assert "ingest_file" in tool_names
        assert "ingest_status" in tool_names

    @pytest.mark.asyncio
    async def test_ingest_url_tool_schema(self):
        """Test ingest_url tool schema."""
        tool = next(t for t in INGESTION_TOOLS if t.name == "ingest_url")
        assert tool.inputSchema.required == ["url"]
        assert "collection" in tool.inputSchema.properties
        assert "metadata" in tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_ingest_file_tool_schema(self):
        """Test ingest_file tool schema."""
        tool = next(t for t in INGESTION_TOOLS if t.name == "ingest_file")
        assert tool.inputSchema.required == ["path"]
        assert "collection" in tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_ingest_status_tool_schema(self):
        """Test ingest_status tool schema."""
        tool = next(t for t in INGESTION_TOOLS if t.name == "ingest_status")
        assert tool.inputSchema.required == ["job_id"]

    @pytest.mark.asyncio
    async def test_validate_ingest_url(self):
        """Test ingest_url validation."""
        valid, error = validate_tool_call("ingest_url", {"url": "https://example.com"})
        assert valid

        valid, error = validate_tool_call("ingest_url", {})
        assert not valid
        assert "url" in error

    @pytest.mark.asyncio
    async def test_get_tools(self, mock_server):
        """Test get_tools returns correct tools."""
        result = mock_server.get_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 3

    @pytest.mark.asyncio
    async def test_get_resources(self, mock_server):
        """Test get_resources returns correct resources."""
        result = mock_server.get_resources()
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 1
        assert result.resources[0].uri == "job://{id}"

    @pytest.mark.asyncio
    async def test_handle_unknown_tool(self, mock_server):
        """Test handling unknown tool."""
        params = ToolCallParams(name="unknown_tool", arguments={})
        result = await mock_server.handle_tool_call(params)
        assert result.isError


class TestAdminServer:
    """Tests for Admin Server."""

    @pytest.fixture
    def mock_server(self):
        """Create a mocked admin server."""
        from contextforge.mcp.servers.admin import AdminServer
        server = AdminServer()
        server._initialized = True
        return server

    @pytest.mark.asyncio
    async def test_admin_tools_exist(self):
        """Test that admin tools are defined."""
        tool_names = [t.name for t in ADMIN_TOOLS]
        assert "get_metrics" in tool_names
        assert "update_config" in tool_names
        assert "trigger_eval" in tool_names

    @pytest.mark.asyncio
    async def test_get_metrics_tool_schema(self):
        """Test get_metrics tool schema."""
        tool = next(t for t in ADMIN_TOOLS if t.name == "get_metrics")
        assert "include_details" in tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_update_config_tool_schema(self):
        """Test update_config tool schema."""
        tool = next(t for t in ADMIN_TOOLS if t.name == "update_config")
        assert tool.inputSchema.required == ["key", "value"]
        assert "persist" in tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_trigger_eval_tool_schema(self):
        """Test trigger_eval tool schema."""
        tool = next(t for t in ADMIN_TOOLS if t.name == "trigger_eval")
        assert tool.inputSchema.required == ["dataset"]
        assert "metrics" in tool.inputSchema.properties
        assert "config" in tool.inputSchema.properties

    @pytest.mark.asyncio
    async def test_validate_update_config(self):
        """Test update_config validation."""
        valid, error = validate_tool_call("update_config", {"key": "LOG_LEVEL", "value": "DEBUG"})
        assert valid

        valid, error = validate_tool_call("update_config", {"key": "LOG_LEVEL"})
        assert not valid
        assert "value" in error

    @pytest.mark.asyncio
    async def test_get_tools(self, mock_server):
        """Test get_tools returns correct tools."""
        result = mock_server.get_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 3

    @pytest.mark.asyncio
    async def test_get_resources(self, mock_server):
        """Test get_resources returns correct resources."""
        result = mock_server.get_resources()
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 1
        assert result.resources[0].uri == "config://{key}"


class TestSchemaValidation:
    """Tests for schema validation utilities."""

    def test_validate_tool_call_valid(self):
        """Test valid tool call."""
        valid, error = validate_tool_call("search", {"query": "test", "k": 5})
        assert valid
        assert error is None

    def test_validate_tool_call_missing_required(self):
        """Test tool call with missing required field."""
        valid, error = validate_tool_call("search", {"k": 5})
        assert not valid
        assert "query" in error

    def test_validate_tool_call_unknown_tool(self):
        """Test unknown tool."""
        valid, error = validate_tool_call("nonexistent", {})
        assert not valid
        assert "Unknown tool" in error

    def test_validate_resource_read_document(self):
        """Test document resource validation."""
        valid, error = validate_resource_read("document://doc-123")
        assert valid

    def test_validate_resource_read_collection(self):
        """Test collection resource validation."""
        valid, error = validate_resource_read("collection://default")
        assert valid

    def test_validate_resource_read_job(self):
        """Test job resource validation."""
        valid, error = validate_resource_read("job://job-123")
        assert valid

    def test_validate_resource_read_config(self):
        """Test config resource validation."""
        valid, error = validate_resource_read("config://LOG_LEVEL")
        assert valid

    def test_validate_resource_read_unknown(self):
        """Test unknown resource."""
        valid, error = validate_resource_read("unknown://something")
        assert not valid
        assert "Unknown resource URI" in error


class TestToolSchemas:
    """Tests for tool schema definitions."""

    def test_all_tools_have_unique_names(self):
        """Test all tools have unique names."""
        from contextforge.mcp.schema import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))

    def test_all_tools_have_input_schema(self):
        """Test all tools have input schema."""
        from contextforge.mcp.schema import ALL_TOOLS
        for tool in ALL_TOOLS:
            assert tool.inputSchema is not None
            assert tool.inputSchema.type == "object"

    def test_all_resources_have_unique_uris(self):
        """Test all resources have unique URI patterns."""
        from contextforge.mcp.schema import ALL_RESOURCES
        uris = [r.uri for r in ALL_RESOURCES]
        assert len(uris) == len(set(uris))

    def test_tool_schema_versioning(self):
        """Test tool schemas have version."""
        from contextforge.mcp.schema import ALL_TOOLS
        for tool in ALL_TOOLS:
            assert tool.version is not None
            assert tool.version.value in ["1.0", "1.1", "2024-11-05", "2025-06-18"]
