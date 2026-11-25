"""
Integration tests for MCP Gateway.

Tests the full MCP Gateway with authentication, rate limiting, routing, and transports.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from contextforge.mcp.auth import AuthProvider, MCPAuth, OAuth21Config, PKCEChallenge
from contextforge.mcp.gateway import AuditLogger, GatewayConfig, MCPGateway
from contextforge.mcp.schema import (
    InitializeParams,
    ListToolsResult,
    MCPError,
    MCPRequest,
    MCPResponse,
    SchemaVersion,
    ToolCallParams,
    ToolCallResult,
)
from contextforge.mcp.transport import (
    SSETransport,
    StreamableHTTPTransport,
    TransportConfig,
    TransportType,
)


class TestMCPGateway:
    """Tests for MCP Gateway."""

    @pytest.fixture
    def gateway_config(self):
        """Create test gateway config."""
        return GatewayConfig(
            auth_enabled=False,  # Disable auth for testing
            rate_limit_enabled=False,
            audit_enabled=False,
        )

    @pytest.fixture
    async def gateway(self, gateway_config):
        """Create gateway instance."""
        gw = MCPGateway(gateway_config)
        # Mock sub-servers
        gw.knowledge_server = AsyncMock()
        gw.ingestion_server = AsyncMock()
        gw.admin_server = AsyncMock()
        yield gw
        await gw.close()

    @pytest.mark.asyncio
    async def test_gateway_initialization(self, gateway):
        """Test gateway initializes correctly."""
        assert gateway.config.auth_enabled is False
        assert gateway.config.rate_limit_enabled is False
        assert gateway.knowledge_server is not None
        assert gateway.ingestion_server is not None
        assert gateway.admin_server is not None

    @pytest.mark.asyncio
    async def test_handle_initialize(self, gateway):
        """Test initialize request handling."""
        request = MCPRequest(
            id="test-1",
            method="initialize",
            params={"protocolVersion": "2024-11-05", "capabilities": {}},
        )

        response = await gateway.handle_mcp_request(
            request=request,
            session_id=None,
            client_id="test-client",
            transport="http",
        )

        assert response.id == "test-1"
        assert response.result is not None
        assert response.error is None
        assert "protocolVersion" in response.result
        assert "capabilities" in response.result
        assert "serverInfo" in response.result

    @pytest.mark.asyncio
    async def test_handle_list_tools(self, gateway):
        """Test tools/list request handling."""
        # Mock server response
        gateway.knowledge_server.get_tools.return_value = ListToolsResult(tools=[])
        gateway.ingestion_server.get_tools.return_value = ListToolsResult(tools=[])
        gateway.admin_server.get_tools.return_value = ListToolsResult(tools=[])

        request = MCPRequest(id="test-2", method="tools/list")
        response = await gateway.handle_mcp_request(
            request=request,
            session_id="session-1",
            client_id="test-client",
            transport="http",
        )

        assert response.id == "test-2"
        assert response.result is not None
        assert "tools" in response.result

    @pytest.mark.asyncio
    async def test_handle_tool_call_routes_to_knowledge(self, gateway):
        """Test tool call routes to knowledge server."""
        expected_result = ToolCallResult(
            content=[{"type": "text", "text": '{"results": []}'}],
            structuredContent={"results": []},
        )
        gateway.knowledge_server.handle_tool_call.return_value = expected_result

        request = MCPRequest(
            id="test-3",
            method="tools/call",
            params={"name": "search", "arguments": {"query": "test"}},
        )

        response = await gateway.handle_mcp_request(
            request=request,
            session_id="session-1",
            client_id="test-client",
            transport="http",
        )

        assert response.id == "test-3"
        assert response.result is not None
        gateway.knowledge_server.handle_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_tool_call_routes_to_ingestion(self, gateway):
        """Test tool call routes to ingestion server."""
        expected_result = ToolCallResult(
            content=[{"type": "text", "text": '{"job_id": "123"}'}],
            structuredContent={"job_id": "123"},
        )
        gateway.ingestion_server.handle_tool_call.return_value = expected_result

        request = MCPRequest(
            id="test-4",
            method="tools/call",
            params={"name": "ingest_url", "arguments": {"url": "https://example.com"}},
        )

        response = await gateway.handle_mcp_request(
            request=request,
            session_id="session-1",
            client_id="test-client",
            transport="http",
        )

        assert response.id == "test-4"
        gateway.ingestion_server.handle_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_tool_call_routes_to_admin(self, gateway):
        """Test tool call routes to admin server."""
        expected_result = ToolCallResult(
            content=[{"type": "text", "text": '{"status": "healthy"}'}],
            structuredContent={"status": "healthy"},
        )
        gateway.admin_server.handle_tool_call.return_value = expected_result

        request = MCPRequest(
            id="test-5",
            method="tools/call",
            params={"name": "get_metrics", "arguments": {}},
        )

        response = await gateway.handle_mcp_request(
            request=request,
            session_id="session-1",
            client_id="test-client",
            transport="http",
        )

        assert response.id == "test-5"
        gateway.admin_server.handle_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_unknown_tool(self, gateway):
        """Test unknown tool returns error."""
        request = MCPRequest(
            id="test-6",
            method="tools/call",
            params={"name": "unknown_tool", "arguments": {}},
        )

        response = await gateway.handle_mcp_request(
            request=request,
            session_id="session-1",
            client_id="test-client",
            transport="http",
        )

        # MCP returns tool errors in result with isError: true
        assert response.result is not None
        assert response.result.get("isError") is True
        assert "Unknown tool" in str(response.result.get("content", [{}])[0].get("text", ""))


class TestSSETransport:
    """Tests for SSE Transport."""

    @pytest.fixture
    def transport_config(self):
        """Create test transport config."""
        return TransportConfig(
            type=TransportType.SSE,
            sse_endpoint="/mcp/sse",
            streamable_endpoint="/mcp",
            message_endpoint="/mcp/message",
        )

    @pytest.fixture
    def sse_transport(self, transport_config):
        """Create SSE transport."""
        return SSETransport(transport_config)

    @pytest.mark.asyncio
    async def test_create_session(self, sse_transport):
        """Test session creation."""
        session = sse_transport.create_session("test-client", TransportType.SSE)
        assert session.client_id == "test-client"
        assert session.transport_type == TransportType.SSE
        assert session.session_id is not None

    @pytest.mark.asyncio
    async def test_get_session(self, sse_transport):
        """Test getting session."""
        session = sse_transport.create_session("test-client", TransportType.SSE)
        retrieved = sse_transport.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_close_session(self, sse_transport):
        """Test closing session."""
        session = sse_transport.create_session("test-client", TransportType.SSE)
        await sse_transport.close_session(session.session_id)
        assert sse_transport.get_session(session.session_id) is None


class TestStreamableHTTPTransport:
    """Tests for Streamable HTTP Transport."""

    @pytest.fixture
    def transport_config(self):
        """Create test transport config."""
        return TransportConfig(
            type=TransportType.STREAMABLE_HTTP,
            sse_endpoint="/mcp/sse",
            streamable_endpoint="/mcp",
            message_endpoint="/mcp/message",
        )

    @pytest.fixture
    def streamable_transport(self, transport_config):
        """Create Streamable HTTP transport."""
        return StreamableHTTPTransport(transport_config)

    @pytest.mark.asyncio
    async def test_create_session(self, streamable_transport):
        """Test session creation."""
        session = streamable_transport.create_session("test-client", TransportType.STREAMABLE_HTTP)
        assert session.client_id == "test-client"
        assert session.transport_type == TransportType.STREAMABLE_HTTP

    @pytest.mark.asyncio
    async def test_handle_regular_post(self, streamable_transport):
        """Test handling regular POST request."""
        # Create a mock request
        from unittest.mock import AsyncMock
        request = AsyncMock()
        request.method = "POST"
        request.headers = {"Accept": "application/json"}
        request.body = AsyncMock(return_value=json.dumps({
            "jsonrpc": "2.0",
            "id": "test-1",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"}
        }).encode())

        # We can't easily test the full request handling without a real request object
        # This is a placeholder for the test structure
        assert streamable_transport is not None


class TestAuth:
    """Tests for Authentication."""

    @pytest.fixture
    def auth_config(self):
        """Create test auth config."""
        return OAuth21Config(
            provider=AuthProvider.DEV,
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="http://localhost:8001",
            redirect_uri="http://localhost:8001/callback",
            pkce_required=False,
        )

    @pytest.fixture
    async def auth(self, auth_config):
        """Create auth instance."""
        a = MCPAuth(auth_config)
        yield a
        await a.close()

    @pytest.mark.asyncio
    async def test_dev_mode_authorization_url(self, auth):
        """Test dev mode authorization URL generation."""
        url = await auth.get_authorization_url()
        assert "dev-code-" in url
        assert "code=" in url

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_dev(self, auth):
        """Test token exchange in dev mode."""
        # First get a code
        url = await auth.get_authorization_url()
        code = url.split("code=")[1].split("&")[0]

        token = await auth.exchange_code_for_token(code=code)
        assert token.access_token
        assert token.token_type.value == "Bearer"
        assert token.refresh_token

    @pytest.mark.asyncio
    async def test_validate_dev_token(self, auth):
        """Test validating dev token."""
        url = await auth.get_authorization_url()
        code = url.split("code=")[1].split("&")[0]
        token = await auth.exchange_code_for_token(code=code)

        payload = await auth.validate_token(token.access_token)
        assert payload.sub == "dev-user"
        assert payload.client_id == "test-client"

    @pytest.mark.asyncio
    async def test_pkce_challenge(self, auth):
        """Test PKCE challenge generation and verification."""
        challenge = PKCEChallenge.generate()
        assert challenge.code_verifier
        assert challenge.code_challenge
        assert challenge.code_challenge_method == "S256"

        # Verify correct verifier
        assert challenge.verify(challenge.code_verifier)

        # Verify incorrect verifier fails
        assert not challenge.verify("wrong-verifier")

    @pytest.mark.asyncio
    async def test_refresh_token(self, auth):
        """Test token refresh."""
        url = await auth.get_authorization_url()
        code = url.split("code=")[1].split("&")[0]
        token = await auth.exchange_code_for_token(code=code)

        new_token = await auth.refresh_access_token(token.refresh_token)
        assert new_token.access_token
        assert new_token.refresh_token == token.refresh_token


class TestRateLimiting:
    """Tests for Rate Limiting."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = AsyncMock()
        # Create a single pipeline mock that's returned every time
        pipeline_mock = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipeline_mock)
        redis.zremrangebyscore = AsyncMock()
        redis.zcard = AsyncMock(return_value=0)
        redis.zadd = AsyncMock()
        redis.expire = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_token_bucket_allows_within_limit(self, mock_redis):
        """Test token bucket allows requests within limit."""
        from contextforge.mcp.gateway import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(mock_redis)
        mock_redis.pipeline.return_value.execute = AsyncMock(return_value=[None, 0, None, None])

        allowed, info = await limiter.is_allowed("client-1", limit=60, burst=10)
        assert allowed
        assert info.remaining == 59

    @pytest.mark.asyncio
    async def test_token_bucket_blocks_over_limit(self, mock_redis):
        """Test token bucket blocks requests over limit."""
        from contextforge.mcp.gateway import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(mock_redis)
        # Simulate 60 existing requests - first execute returns count=60, second is for adding (not called since blocked)
        pipeline_mock = mock_redis.pipeline.return_value
        pipeline_mock.execute.side_effect = [[None, 60], [None, None]]

        allowed, info = await limiter.is_allowed("client-1", limit=60, burst=10)
        assert not allowed
        assert info.remaining == 0


class TestAuditLogger:
    """Tests for Audit Logger."""

    @pytest.fixture
    def audit_logger(self):
        """Create audit logger."""
        return AuditLogger(enabled=True)

    @pytest.mark.asyncio
    async def test_log_entry(self, audit_logger):
        """Test logging an entry."""
        await audit_logger.log(
            client_id="client-1",
            session_id="session-1",
            tool_name="search",
            tool_args={"query": "test"},
            tool_result={"results": []},
            latency_ms=10.5,
            status="success",
            transport="http",
        )

        assert len(audit_logger._buffer) == 1
        entry = audit_logger._buffer[0]
        assert entry.client_id == "client-1"
        assert entry.tool_name == "search"
        assert entry.status == "success"

    @pytest.mark.asyncio
    async def test_disabled_logger(self):
        """Test disabled logger doesn't log."""
        logger = AuditLogger(enabled=False)
        await logger.log(
            client_id="client-1",
            session_id="session-1",
            tool_name="search",
            tool_args={"query": "test"},
            tool_result={"results": []},
            latency_ms=10.5,
            status="success",
            transport="http",
        )
        assert len(logger._buffer) == 0


class TestSchemaVersioning:
    """Tests for Schema Versioning."""

    def test_schema_version_enum(self):
        """Test schema version enum values."""
        assert SchemaVersion.V1_0.value == "1.0"
        assert SchemaVersion.V1_1.value == "1.1"
        assert SchemaVersion.V2024_11_05.value == "2024-11-05"
        assert SchemaVersion.V2025_06_18.value == "2025-06-18"

    def test_schema_version_latest(self):
        """Test latest version."""
        assert SchemaVersion.latest() == SchemaVersion.V2025_06_18

    def test_schema_version_default(self):
        """Test default version."""
        assert SchemaVersion.default() == SchemaVersion.V2024_11_05


class TestMCPProtocol:
    """Tests for MCP Protocol Messages."""

    def test_mcp_request_validation(self):
        """Test MCP request validation."""
        request = MCPRequest(
            id="test-1",
            method="tools/list",
            params={},
        )
        assert request.jsonrpc == "2.0"
        assert request.method == "tools/list"

    def test_mcp_request_invalid_method(self):
        """Test MCP request rejects invalid method."""
        with pytest.raises(ValueError):
            MCPRequest(id="test-1", method="invalid/method")

    def test_mcp_response_success(self):
        """Test MCP success response."""
        response = MCPResponse(
            id="test-1",
            result={"tools": []},
        )
        assert response.result is not None
        assert response.error is None

    def test_mcp_response_error(self):
        """Test MCP error response."""
        response = MCPResponse(
            id="test-1",
            error=MCPError(code=-32601, message="Method not found"),
        )
        assert response.error is not None
        assert response.result is None

    def test_mcp_response_both_result_and_error_fails(self):
        """Test response with both result and error fails."""
        with pytest.raises(ValueError):
            MCPResponse(
                id="test-1",
                result={},
                error=MCPError(code=-32601, message="Error"),
            )

    def test_initialize_params(self):
        """Test initialize params."""
        params = InitializeParams(
            protocolVersion=SchemaVersion.V2024_11_05,
            capabilities={"tools": {}},
            clientInfo={"name": "test-client", "version": "1.0"},
        )
        assert params.protocolVersion == SchemaVersion.V2024_11_05

    def test_tool_call_params(self):
        """Test tool call params."""
        params = ToolCallParams(
            name="search",
            arguments={"query": "test", "k": 10},
            requestId="req-1",
        )
        assert params.name == "search"
        assert params.arguments["query"] == "test"
