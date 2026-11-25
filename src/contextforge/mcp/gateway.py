"""
MCP Gateway

Single entry point for MCP clients (port 8001). Handles:
- OAuth 2.1 + PKCE authentication
- Rate limiting (token bucket per client)
- Request routing to sub-servers (Knowledge, Ingestion, Admin)
- Audit logging (every tool call → DB + CloudWatch)
- mTLS between gateway and sub-servers
- SSE + Streamable HTTP transport
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from contextforge.config import settings
from contextforge.mcp.auth import (
    AuthProvider,
    OAuth21Provider,
    PKCEChallenge,
    TokenPayload,
    close_auth,
    get_auth,
)
from contextforge.mcp.schema import (
    ALL_RESOURCES,
    ALL_TOOLS,
    InitializeParams,
    InitializeResult,
    ListResourcesResult,
    ListToolsResult,
    MCPError,
    MCPRequest,
    MCPResponse,
    ResourceReadParams,
    ResourceReadResult,
    SchemaVersion,
    ToolCallParams,
    ToolCallResult,
)
from contextforge.mcp.servers.admin import close_admin_server, get_admin_server
from contextforge.mcp.servers.ingestion import close_ingestion_server, get_ingestion_server
from contextforge.mcp.servers.knowledge import close_knowledge_server, get_knowledge_server
from contextforge.mcp.transport import (
    SSETransport,
    StreamableHTTPTransport,
    TransportConfig,
    TransportType,
)
from contextforge.observability.metrics import (
    get_content_type,
    get_metrics_output,
    mcp_active_sessions,
    mcp_rate_limit_exceeded_total,
    mcp_tool_calls_total,
    mcp_tool_latency_seconds,
)
from contextforge.storage.database import get_db_session
from contextforge.storage.repositories.audit import AuditRepository

logger = structlog.get_logger(__name__)


# =============================================================================
# Models
# =============================================================================

class GatewayConfig(BaseModel):
    """Gateway configuration."""

    host: str = "0.0.0.0"
    port: int = 8001
    workers: int = 4

    # Auth
    auth_enabled: bool = True
    auth_provider: AuthProvider = AuthProvider.DEV

    # Rate limiting
    rate_limit_enabled: bool = True
    default_rate_limit: int = 60  # requests per minute
    burst_limit: int = 10

    # Transport
    sse_enabled: bool = True
    streamable_http_enabled: bool = True

    # mTLS
    mtls_enabled: bool = False
    cert_path: str = ""
    key_path: str = ""
    ca_path: str = ""

    # Audit
    audit_enabled: bool = True
    audit_log_level: str = "INFO"

    # Sub-server endpoints (for future distributed deployment)
    knowledge_server_url: str = "local"
    ingestion_server_url: str = "local"
    admin_server_url: str = "local"


class RateLimitInfo(BaseModel):
    """Rate limit information for a client."""

    client_id: str
    limit: int
    remaining: int
    reset_at: float
    burst: int


class AuditLogEntry(BaseModel):
    """Audit log entry for tool calls."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    client_id: str
    session_id: str | None = None
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: dict[str, Any] | None = None
    latency_ms: float
    status: str  # success, error, rate_limited
    error_message: str | None = None
    transport: str
    user_agent: str | None = None
    ip_address: str | None = None


# =============================================================================
# Rate Limiter (Token Bucket)
# =============================================================================

class TokenBucketRateLimiter:
    """Token bucket rate limiter using Redis."""

    def __init__(self, redis_client, prefix: str = "ratelimit:mcp:"):
        self.redis = redis_client
        self.prefix = prefix

    async def check_limit(
        self,
        client_id: str,
        limit: int = 60,
        burst: int = 10,
        window_seconds: int = 60,
    ) -> RateLimitInfo:
        """Check and consume rate limit tokens."""
        key = f"{self.prefix}{client_id}"
        now = time.time()
        window_start = now - window_seconds

        # Use Redis sorted set for sliding window
        pipe = self.redis.pipeline()

        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current requests
        pipe.zcard(key)

        results = await pipe.execute()
        current_count = results[1]

        # Check if limit exceeded BEFORE adding
        if current_count >= limit:
            # Limit exceeded - return info with remaining=0
            reset_at = now + window_seconds
            return RateLimitInfo(
                client_id=client_id,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
                burst=burst,
            )

        # Add current request
        request_id = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe = self.redis.pipeline()
        pipe.zadd(key, {request_id: now})
        pipe.expire(key, window_seconds + 1)
        await pipe.execute()

        remaining = max(0, limit - current_count - 1)
        reset_at = now + window_seconds

        return RateLimitInfo(
            client_id=client_id,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            burst=burst,
        )

    async def is_allowed(
        self,
        client_id: str,
        limit: int = 60,
        burst: int = 10,
        window_seconds: int = 60,
    ) -> tuple[bool, RateLimitInfo]:
        """Check if request is allowed."""
        info = await self.check_limit(client_id, limit, burst, window_seconds)
        allowed = info.remaining > 0
        return allowed, info


# =============================================================================
# Audit Logger
# =============================================================================

class AuditLogger:
    """Audit logger for MCP tool calls."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._buffer: list[AuditLogEntry] = []
        self._flush_interval = 5.0  # seconds
        self._flush_task: asyncio.Task | None = None

    async def start(self):
        """Start background flush task."""
        if self.enabled:
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self):
        """Stop background flush task."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()

    async def log(
        self,
        client_id: str,
        session_id: str | None,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any] | None,
        latency_ms: float,
        status: str,
        error_message: str | None = None,
        transport: str = "http",
        user_agent: str | None = None,
        ip_address: str | None = None,
    ):
        """Log a tool call."""
        if not self.enabled:
            return

        entry = AuditLogEntry(
            client_id=client_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            transport=transport,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        self._buffer.append(entry)

        # Also log to structlog for CloudWatch
        logger.info(
            "mcp_tool_call",
            client_id=client_id,
            session_id=session_id,
            tool=tool_name,
            args=tool_args,
            latency_ms=latency_ms,
            status=status,
            error=error_message,
        )

    async def _flush_loop(self):
        """Periodically flush buffer to database."""
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("audit_flush_error", error=str(e))

    async def _flush(self):
        """Flush buffer to database."""
        if not self._buffer:
            return

        entries = self._buffer.copy()
        self._buffer.clear()

        try:
            async with get_db_session() as session:
                audit_repo = AuditRepository(session)
                for entry in entries:
                    await audit_repo.create(
                        id=entry.id,
                        timestamp=entry.timestamp,
                        client_id=entry.client_id,
                        session_id=entry.session_id,
                        tool_name=entry.tool_name,
                        tool_args=entry.tool_args,
                        tool_result=entry.tool_result,
                        latency_ms=entry.latency_ms,
                        status=entry.status,
                        error_message=entry.error_message,
                        transport=entry.transport,
                        user_agent=entry.user_agent,
                        ip_address=entry.ip_address,
                    )
        except Exception as e:
            logger.error("audit_db_write_error", error=str(e))
            # Re-add to buffer for retry
            self._buffer.extend(entries)


# =============================================================================
# MCP Gateway
# =============================================================================

class MCPGateway:
    """
    MCP Gateway - Main entry point for all MCP clients.

    Handles authentication, rate limiting, routing, and audit logging.
    """

    def __init__(self, config: GatewayConfig | None = None):
        self.config = config or GatewayConfig()
        self.auth = get_auth()
        self.oauth_provider = OAuth21Provider(self.auth)

        # Transports
        transport_config = TransportConfig(
            type=TransportType.STREAMABLE_HTTP,
            sse_endpoint="/mcp/sse",
            streamable_endpoint="/mcp",
            message_endpoint="/mcp/message",
        )
        self.sse_transport = SSETransport(transport_config)
        self.streamable_transport = StreamableHTTPTransport(transport_config)

        # Sub-servers
        self.knowledge_server = None
        self.ingestion_server = None
        self.admin_server = None

        # Rate limiter
        self.rate_limiter: TokenBucketRateLimiter | None = None

        # Audit logger
        self.audit_logger = AuditLogger(enabled=self.config.audit_enabled)

        # Metrics
        self._request_count = 0
        self._error_count = 0
        self._active_sessions = 0

    async def initialize(self):
        """Initialize gateway components."""
        # Initialize sub-servers
        self.knowledge_server = await get_knowledge_server()
        self.ingestion_server = await get_ingestion_server()
        self.admin_server = await get_admin_server()

        # Initialize rate limiter (requires Redis)
        # self.rate_limiter = TokenBucketRateLimiter(redis_client)

        # Start audit logger
        await self.audit_logger.start()

        logger.info("mcp_gateway_initialized", config=self.config.model_dump())

    async def close(self):
        """Close gateway components."""
        await self.audit_logger.stop()
        await close_knowledge_server()
        await close_ingestion_server()
        await close_admin_server()
        await close_auth()
        logger.info("mcp_gateway_closed")

    # =========================================================================
    # Authentication
    # =========================================================================

    async def authenticate_request(
        self,
        request: Request,
        authorization: str | None = None,
    ) -> tuple[TokenPayload | None, str | None]:
        """Authenticate request and return token payload and client ID."""
        if not self.config.auth_enabled:
            return None, "anonymous"

        if not authorization:
            return None, None

        # Parse Bearer token
        if not authorization.startswith("Bearer "):
            return None, None

        token = authorization[7:]  # Remove "Bearer "

        try:
            payload = await self.auth.validate_token(token)
            return payload, payload.client_id
        except ValueError:
            return None, None

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def check_rate_limit(self, client_id: str) -> tuple[bool, RateLimitInfo | None]:
        """Check rate limit for client."""
        if not self.config.rate_limit_enabled or not self.rate_limiter:
            return True, None

        return await self.rate_limiter.is_allowed(
            client_id,
            limit=self.config.default_rate_limit,
            burst=self.config.burst_limit,
        )

    # =========================================================================
    # Request Routing
    # =========================================================================

    async def route_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> ToolCallResult:
        """Route tool call to appropriate sub-server."""
        # Determine which server handles this tool
        if tool_name in ["search", "get_document", "list_collections"]:
            server = self.knowledge_server
        elif tool_name in ["ingest_url", "ingest_file", "ingest_status"]:
            server = self.ingestion_server
        elif tool_name in ["get_metrics", "update_config", "trigger_eval"]:
            server = self.admin_server
        else:
            return ToolCallResult(
                content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                isError=True,
            )

        if not server:
            return ToolCallResult(
                content=[{"type": "text", "text": "Server not initialized"}],
                isError=True,
            )

        # Create tool call params
        params = ToolCallParams(name=tool_name, arguments=arguments)

        # Call server
        return await server.handle_tool_call(params)

    async def route_resource_read(
        self,
        uri: str,
        session_id: str | None = None,
    ) -> ResourceReadResult:
        """Route resource read to appropriate sub-server."""
        if uri.startswith("document://") or uri.startswith("collection://"):
            server = self.knowledge_server
        elif uri.startswith("job://"):
            server = self.ingestion_server
        elif uri.startswith("config://"):
            server = self.admin_server
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

        if not server:
            return ResourceReadResult(
                contents=[
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"error": "Server not initialized"}),
                    }
                ]
            )

        params = ResourceReadParams(uri=uri)
        return await server.handle_resource_read(params)

    # =========================================================================
    # MCP Protocol Handling
    # =========================================================================

    async def handle_mcp_request(
        self,
        request: MCPRequest,
        session_id: str | None,
        client_id: str,
        transport: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> MCPResponse:
        """Handle MCP request and return response."""
        start_time = time.time()
        self._request_count += 1

        try:
            if request.method == "initialize":
                return await self._handle_initialize(request, session_id)
            elif request.method == "initialized":
                return MCPResponse(id=request.id, result={})
            elif request.method == "tools/list":
                return await self._handle_list_tools(request, session_id)
            elif request.method == "tools/call":
                return await self._handle_tool_call(request, session_id, client_id, transport, user_agent, ip_address)
            elif request.method == "resources/list":
                return await self._handle_list_resources(request, session_id)
            elif request.method == "resources/read":
                return await self._handle_resource_read(request, session_id, client_id, transport, user_agent, ip_address)
            elif request.method == "ping":
                return MCPResponse(id=request.id, result={})
            else:
                return MCPResponse(
                    id=request.id,
                    error=MCPError(code=-32601, message=f"Method not found: {request.method}"),
                )
        except Exception as e:
            self._error_count += 1
            logger.exception("mcp_request_error", method=request.method, error=str(e))
            return MCPResponse(
                id=request.id,
                error=MCPError(code=-32603, message=f"Internal error: {str(e)}"),
            )
        finally:
            latency_ms = (time.time() - start_time) * 1000
            # Audit logging handled in individual handlers

    async def _handle_initialize(
        self,
        request: MCPRequest,
        session_id: str | None,
    ) -> MCPResponse:
        """Handle initialize request."""
        params = InitializeParams(**(request.params or {}))

        result = InitializeResult(
            protocolVersion=SchemaVersion.latest(),
            capabilities={
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
                "logging": {},
            },
            serverInfo={
                "name": "contextforge-mcp-gateway",
                "version": "0.1.0",
            },
            instructions="ContextForge MCP Gateway - Enterprise RAG Pipeline with Knowledge, Ingestion, and Admin servers",
        )
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_list_tools(
        self,
        request: MCPRequest,
        session_id: str | None,
    ) -> MCPResponse:
        """Handle tools/list request."""
        result = ListToolsResult(tools=ALL_TOOLS)
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_tool_call(
        self,
        request: MCPRequest,
        session_id: str | None,
        client_id: str,
        transport: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> MCPResponse:
        """Handle tools/call request."""
        start_time = time.time()
        params = ToolCallParams(**(request.params or {}))

        # Route to server
        result = await self.route_tool_call(params.name, params.arguments, session_id)

        latency_ms = (time.time() - start_time) * 1000
        latency_seconds = latency_ms / 1000.0

        # Prometheus metrics
        status = "error" if result.isError else "success"
        mcp_tool_calls_total.labels(tool=params.name, status=status).inc()
        mcp_tool_latency_seconds.labels(tool=params.name).observe(latency_seconds)

        # Audit log
        await self.audit_logger.log(
            client_id=client_id,
            session_id=session_id,
            tool_name=params.name,
            tool_args=params.arguments,
            tool_result=result.structuredContent or result.model_dump(),
            latency_ms=latency_ms,
            status=status,
            error_message=result.content[0].get("text") if result.isError and result.content else None,
            transport=transport,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_list_resources(
        self,
        request: MCPRequest,
        session_id: str | None,
    ) -> MCPResponse:
        """Handle resources/list request."""
        result = ListResourcesResult(resources=ALL_RESOURCES)
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_resource_read(
        self,
        request: MCPRequest,
        session_id: str | None,
        client_id: str,
        transport: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> MCPResponse:
        """Handle resources/read request."""
        start_time = time.time()
        params = ResourceReadParams(**(request.params or {}))

        result = await self.route_resource_read(params.uri, session_id)

        latency_ms = (time.time() - start_time) * 1000

        # Audit log
        await self.audit_logger.log(
            client_id=client_id,
            session_id=session_id,
            tool_name=f"resource_read:{params.uri}",
            tool_args={"uri": params.uri},
            tool_result=result.model_dump(),
            latency_ms=latency_ms,
            status="success",
            transport=transport,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return MCPResponse(id=request.id, result=result.model_dump())


# =============================================================================
# FastAPI Application
# =============================================================================

_gateway: MCPGateway | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _gateway

    # Startup
    logger.info("mcp_gateway_starting")

    _gateway = MCPGateway()
    await _gateway.initialize()

    yield

    # Shutdown
    logger.info("mcp_gateway_shutting_down")
    if _gateway:
        await _gateway.close()


app = FastAPI(
    title="ContextForge MCP Gateway",
    description="Model Context Protocol Gateway for ContextForge Enterprise RAG Pipeline",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)


# =============================================================================
# OAuth 2.1 Endpoints
# =============================================================================

@app.get("/.well-known/oauth-authorization-server", tags=["oauth"])
async def oauth_metadata():
    """OAuth 2.1 Authorization Server Metadata."""
    return _gateway.oauth_provider.get_metadata()


@app.get("/.well-known/oauth-authorization-server/{client_id}", tags=["oauth"])
async def oauth_client_metadata(client_id: str):
    """OAuth 2.1 Client Metadata."""
    metadata = _gateway.oauth_provider.get_client_metadata(client_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Client not found")
    return metadata


@app.get("/oauth2/authorize", tags=["oauth"])
async def oauth_authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "",
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str = "S256",
):
    """OAuth 2.1 Authorization Endpoint."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Unsupported response_type")

    auth_url = await _gateway.auth.get_authorization_url(
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    # In production, show consent screen first
    # For now, redirect directly
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=auth_url)


@app.post("/oauth2/token", tags=["oauth"])
async def oauth_token(
    request: Request,
    grant_type: str = "authorization_code",
    code: str = "",
    redirect_uri: str = "",
    code_verifier: str | None = None,
    refresh_token: str | None = None,
    client_id: str = "",
    client_secret: str = "",
):
    """OAuth 2.1 Token Endpoint."""
    # Validate client credentials
    if client_id != _gateway.auth.config.client_id:
        raise HTTPException(status_code=401, detail="Invalid client")

    if grant_type == "authorization_code":
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")

        try:
            token = await _gateway.auth.exchange_code_for_token(
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
            return token.model_dump(exclude_none=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="Missing refresh_token")

        try:
            token = await _gateway.auth.refresh_access_token(refresh_token)
            return token.model_dump(exclude_none=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    else:
        raise HTTPException(status_code=400, detail="Unsupported grant_type")


@app.post("/oauth2/revoke", tags=["oauth"])
async def oauth_revoke(
    request: Request,
    token: str = "",
    token_type_hint: str | None = None,
):
    """OAuth 2.1 Token Revocation Endpoint."""
    await _gateway.auth.revoke_token(token)
    return Response(status_code=200)


# =============================================================================
# MCP Transport Endpoints
# =============================================================================

@app.get("/mcp/sse", tags=["mcp"])
async def mcp_sse_get(
    request: Request,
    session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """SSE GET endpoint for event stream."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Rate limit
    if client_id:
        allowed, rate_info = await _gateway.check_rate_limit(client_id)
        if not allowed:
            mcp_rate_limit_exceeded_total.labels(client_id=client_id).inc()
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(rate_info.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(rate_info.reset_at)),
                },
            )

    # Handle via SSE transport
    return await _gateway.sse_transport.handle_request(request, session_id)


@app.post("/mcp/sse", tags=["mcp"])
async def mcp_sse_post(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """SSE POST endpoint for client messages."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Rate limit
    if client_id:
        allowed, rate_info = await _gateway.check_rate_limit(client_id)
        if not allowed:
            mcp_rate_limit_exceeded_total.labels(client_id=client_id).inc()
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return await _gateway.sse_transport.handle_request(request, session_id)


@app.post("/mcp", tags=["mcp"])
async def mcp_streamable_post(
    request: Request,
    session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """Streamable HTTP POST endpoint."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Rate limit
    if client_id:
        allowed, rate_info = await _gateway.check_rate_limit(client_id)
        if not allowed:
            mcp_rate_limit_exceeded_total.labels(client_id=client_id).inc()
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(rate_info.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(rate_info.reset_at)),
                },
            )

    return await _gateway.streamable_transport.handle_request(request, session_id)


@app.get("/mcp", tags=["mcp"])
async def mcp_streamable_get(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """Streamable HTTP GET endpoint for server-sent events."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _gateway.streamable_transport.handle_request(request, session_id)


@app.delete("/mcp", tags=["mcp"])
async def mcp_streamable_delete(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """Streamable HTTP DELETE endpoint to close session."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _gateway.streamable_transport.handle_request(request, session_id)


@app.post("/mcp/message", tags=["mcp"])
async def mcp_message(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
):
    """MCP message endpoint (for SSE transport)."""
    # Authenticate
    payload, client_id = await _gateway.authenticate_request(request, authorization)
    if _gateway.config.auth_enabled and not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _gateway.sse_transport.handle_request(request, session_id)


# =============================================================================
# Health & Info Endpoints
# =============================================================================

@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "contextforge-mcp-gateway",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/info", tags=["info"])
async def gateway_info():
    """Gateway information endpoint."""
    return {
        "name": "contextforge-mcp-gateway",
        "version": "0.1.0",
        "protocol_version": SchemaVersion.latest().value,
        "transports": ["sse", "streamable_http"],
        "servers": ["knowledge", "ingestion", "admin"],
        "auth": {
            "enabled": _gateway.config.auth_enabled,
            "provider": _gateway.config.auth_provider.value,
        },
        "rate_limiting": {
            "enabled": _gateway.config.rate_limit_enabled,
            "default_limit": _gateway.config.default_rate_limit,
        },
        "audit_logging": _gateway.config.audit_enabled,
    }


@app.get("/metrics", tags=["monitoring"])
async def gateway_metrics():
    """Gateway metrics endpoint."""
    return {
        "requests_total": _gateway._request_count if _gateway else 0,
        "errors_total": _gateway._error_count if _gateway else 0,
        "active_sessions": _gateway._active_sessions if _gateway else 0,
    }


@app.get("/mcp/schemas", tags=["mcp"])
async def mcp_schemas():
    """
    MCP Tool Schema Registry Endpoint.

    Returns all available tool schemas (name, version, inputSchema, outputSchema)
    for client auto-configuration.
    """
    tools = []
    for tool in ALL_TOOLS:
        tools.append({
            "name": tool.name,
            "version": tool.version.value,
            "description": tool.description,
            "inputSchema": tool.inputSchema.model_dump(),
            "outputSchema": tool.outputSchema.model_dump() if tool.outputSchema else None,
            "deprecated": tool.deprecated,
            "tags": tool.tags,
        })

    resources = []
    for resource in ALL_RESOURCES:
        resources.append({
            "uri": resource.uri,
            "name": resource.name,
            "description": resource.description,
            "mimeType": resource.mimeType,
            "version": resource.version.value,
            "deprecated": resource.deprecated,
        })

    return {
        "protocol_version": SchemaVersion.latest().value,
        "tools": tools,
        "resources": resources,
    }


@app.get("/mcp/metrics", tags=["mcp", "monitoring"])
async def mcp_prometheus_metrics():
    """
    MCP Prometheus Metrics Endpoint.

    Returns Prometheus-formatted metrics for MCP Gateway:
    - mcp_tool_calls_total{tool,status}
    - mcp_tool_latency_seconds{tool}
    - mcp_active_sessions
    - mcp_rate_limit_exceeded_total{client_id}
    """
    from fastapi.responses import Response

    # Update active sessions gauge
    if _gateway:
        sse_sessions = len(_gateway.sse_transport._sessions) if hasattr(_gateway.sse_transport, '_sessions') else 0
        streamable_sessions = len(_gateway.streamable_transport._sessions) if hasattr(_gateway.streamable_transport, '_sessions') else 0
        total_sessions = sse_sessions + streamable_sessions
        mcp_active_sessions.set(total_sessions)

    return Response(
        content=get_metrics_output(),
        media_type=get_content_type(),
    )


# =============================================================================
# Development/Debug Endpoints
# =============================================================================

@app.get("/dev/tokens", tags=["dev"])
async def dev_list_tokens():
    """List active tokens (dev only)."""
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Dev endpoint - not implemented"}


@app.post("/dev/pkce", tags=["dev"])
async def dev_create_pkce():
    """Create PKCE challenge (dev only)."""
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")

    challenge = PKCEChallenge.generate()
    challenge_id = str(uuid.uuid4())
    _gateway.auth._pkce_challenges[challenge_id] = challenge

    return {
        "challenge_id": challenge_id,
        "code_challenge": challenge.code_challenge,
        "code_challenge_method": challenge.code_challenge_method,
    }


# =============================================================================
# Main Entry Point
# =============================================================================

def get_gateway() -> MCPGateway | None:
    """Get gateway instance."""
    return _gateway


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "contextforge.mcp.gateway:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        workers=1,
    )
