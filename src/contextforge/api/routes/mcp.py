"""
MCP API Routes

FastAPI routes for MCP Gateway integration with main API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from contextforge.mcp.auth import get_auth
from contextforge.mcp.gateway import get_gateway
from contextforge.mcp.schema import SchemaVersion

router = APIRouter(prefix="/mcp", tags=["mcp"])


# =============================================================================
# Dependencies
# =============================================================================

async def get_mcp_gateway():
    """Get MCP gateway instance."""
    gateway = get_gateway()
    if not gateway:
        raise HTTPException(status_code=503, detail="MCP Gateway not initialized")
    return gateway


async def authenticate_mcp_request(
    request: Request,
    authorization: str | None = Header(None),
    gateway=Depends(get_mcp_gateway),
):
    """Authenticate MCP request."""
    if not gateway.config.auth_enabled:
        return None, "anonymous"

    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = authorization[7:]
    auth = get_auth()

    try:
        payload = await auth.validate_token(token)
        return payload, payload.client_id
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


async def check_rate_limit(
    request: Request,
    client_id: str = "anonymous",
    gateway=Depends(get_mcp_gateway),
):
    """Check rate limit for client."""
    if not gateway.config.rate_limit_enabled:
        return

    allowed, rate_info = await gateway.check_rate_limit(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(rate_info.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(rate_info.reset_at)),
            },
        )


# =============================================================================
# OAuth 2.1 Endpoints
# =============================================================================

@router.get("/.well-known/oauth-authorization-server", tags=["oauth"])
async def oauth_metadata(gateway=Depends(get_mcp_gateway)):
    """OAuth 2.1 Authorization Server Metadata."""
    return gateway.oauth_provider.get_metadata()


@router.get("/.well-known/oauth-authorization-server/{client_id}", tags=["oauth"])
async def oauth_client_metadata(client_id: str, gateway=Depends(get_mcp_gateway)):
    """OAuth 2.1 Client Metadata."""
    metadata = gateway.oauth_provider.get_client_metadata(client_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Client not found")
    return metadata


@router.get("/oauth2/authorize", tags=["oauth"])
async def oauth_authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "",
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str = "S256",
    gateway=Depends(get_mcp_gateway),
):
    """OAuth 2.1 Authorization Endpoint."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Unsupported response_type")

    auth_url = await gateway.auth.get_authorization_url(
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=auth_url)


@router.post("/oauth2/token", tags=["oauth"])
async def oauth_token(
    request: Request,
    grant_type: str = "authorization_code",
    code: str = "",
    redirect_uri: str = "",
    code_verifier: str | None = None,
    refresh_token: str | None = None,
    client_id: str = "",
    client_secret: str = "",
    gateway=Depends(get_mcp_gateway),
):
    """OAuth 2.1 Token Endpoint."""
    if client_id != gateway.auth.config.client_id:
        raise HTTPException(status_code=401, detail="Invalid client")

    if grant_type == "authorization_code":
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")

        try:
            token = await gateway.auth.exchange_code_for_token(
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
            token = await gateway.auth.refresh_access_token(refresh_token)
            return token.model_dump(exclude_none=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    else:
        raise HTTPException(status_code=400, detail="Unsupported grant_type")


@router.post("/oauth2/revoke", tags=["oauth"])
async def oauth_revoke(
    request: Request,
    token: str = "",
    token_type_hint: str | None = None,
    gateway=Depends(get_mcp_gateway),
):
    """OAuth 2.1 Token Revocation Endpoint."""
    await gateway.auth.revoke_token(token)
    return Response(status_code=200)


# =============================================================================
# SSE Transport Endpoints
# =============================================================================

@router.get("/sse", tags=["mcp"])
async def mcp_sse_get(
    request: Request,
    session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
    _rate_limit=Depends(check_rate_limit),
):
    """SSE GET endpoint for event stream."""
    payload, client_id = auth_result
    return await gateway.sse_transport.handle_request(request, session_id)


@router.post("/sse", tags=["mcp"])
async def mcp_sse_post(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
    _rate_limit=Depends(check_rate_limit),
):
    """SSE POST endpoint for client messages."""
    payload, client_id = auth_result
    return await gateway.sse_transport.handle_request(request, session_id)


# =============================================================================
# Streamable HTTP Transport Endpoints
# =============================================================================

@router.post("", tags=["mcp"])
async def mcp_streamable_post(
    request: Request,
    session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
    _rate_limit=Depends(check_rate_limit),
):
    """Streamable HTTP POST endpoint."""
    payload, client_id = auth_result
    return await gateway.streamable_transport.handle_request(request, session_id)


@router.get("", tags=["mcp"])
async def mcp_streamable_get(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
):
    """Streamable HTTP GET endpoint for server-sent events."""
    payload, client_id = auth_result
    return await gateway.streamable_transport.handle_request(request, session_id)


@router.delete("", tags=["mcp"])
async def mcp_streamable_delete(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
):
    """Streamable HTTP DELETE endpoint to close session."""
    payload, client_id = auth_result
    return await gateway.streamable_transport.handle_request(request, session_id)


@router.post("/message", tags=["mcp"])
async def mcp_message(
    request: Request,
    session_id: str = Header(..., alias="Mcp-Session-Id"),
    auth_result=Depends(authenticate_mcp_request),
    gateway=Depends(get_mcp_gateway),
    _rate_limit=Depends(check_rate_limit),
):
    """MCP message endpoint (for SSE transport)."""
    payload, client_id = auth_result
    return await gateway.sse_transport.handle_request(request, session_id)


# =============================================================================
# Health & Info Endpoints
# =============================================================================

@router.get("/health", tags=["health"])
async def health_check(gateway=Depends(get_mcp_gateway)):
    """MCP Gateway health check."""
    return {
        "status": "healthy",
        "service": "contextforge-mcp-gateway",
        "version": "0.1.0",
        "gateway_initialized": gateway is not None,
    }


@router.get("/info", tags=["info"])
async def gateway_info(gateway=Depends(get_mcp_gateway)):
    """MCP Gateway information."""
    return {
        "name": "contextforge-mcp-gateway",
        "version": "0.1.0",
        "protocol_version": SchemaVersion.latest().value,
        "transports": ["sse", "streamable_http"],
        "servers": ["knowledge", "ingestion", "admin"],
        "auth": {
            "enabled": gateway.config.auth_enabled,
            "provider": gateway.config.auth_provider.value,
        },
        "rate_limiting": {
            "enabled": gateway.config.rate_limit_enabled,
            "default_limit": gateway.config.default_rate_limit,
        },
        "audit_logging": gateway.config.audit_enabled,
    }
