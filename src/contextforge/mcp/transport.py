"""
MCP Transport Layer

Implements SSE (Server-Sent Events) and Streamable HTTP transports per MCP specification.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import Request, Response, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from contextforge.mcp.schema import (
    InitializeParams,
    InitializeResult,
    ListResourcesResult,
    ListToolsResult,
    MCPError,
    MCPMessage,
    MCPRequest,
    MCPResponse,
    ResourceReadParams,
    ResourceReadResult,
    SchemaVersion,
    ToolCallParams,
    ToolCallResult,
)


class TransportType(str, Enum):
    """Supported transport types."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
    WEBSOCKET = "websocket"  # For future use


@dataclass
class TransportConfig:
    """Transport configuration."""

    type: TransportType = TransportType.STREAMABLE_HTTP
    sse_endpoint: str = "/mcp/sse"
    streamable_endpoint: str = "/mcp"
    message_endpoint: str = "/mcp/message"
    max_concurrent_streams: int = 100
    stream_timeout_seconds: int = 300
    heartbeat_interval_seconds: int = 30
    max_message_size: int = 1024 * 1024  # 1MB


class SessionInfo(BaseModel):
    """MCP session information."""

    session_id: str
    client_id: str
    transport_type: TransportType
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    initialized: bool = False
    capabilities: dict[str, Any] = field(default_factory=dict)
    protocol_version: SchemaVersion = SchemaVersion.default()


class TransportBase(ABC):
    """Abstract base class for MCP transports."""

    def __init__(self, config: TransportConfig):
        self.config = config
        self._sessions: dict[str, SessionInfo] = {}
        self._message_queues: dict[str, asyncio.Queue] = {}
        _locks: dict[str, asyncio.Lock] = {}

    @abstractmethod
    async def handle_request(self, request: Request, session_id: str | None) -> Response:
        """Handle incoming HTTP request."""
        pass

    @abstractmethod
    async def send_message(self, session_id: str, message: MCPMessage) -> bool:
        """Send a message to a session."""
        pass

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close a session."""
        pass

    def create_session(self, client_id: str, transport_type: TransportType) -> SessionInfo:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        session = SessionInfo(
            session_id=session_id,
            client_id=client_id,
            transport_type=transport_type,
        )
        self._sessions[session_id] = session
        self._message_queues[session_id] = asyncio.Queue(maxsize=1000)
        return session

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def update_session_activity(self, session_id: str) -> None:
        """Update session last activity timestamp."""
        if session_id in self._sessions:
            self._sessions[session_id].last_activity = datetime.utcnow()

    async def _handle_mcp_request(self, session_id: str, request: MCPRequest) -> MCPResponse:
        """Handle MCP request and return response."""
        session = self.get_session(session_id)
        if not session:
            return MCPResponse(
                id=request.id,
                error=MCPError(code=-32000, message="Session not found"),
            )

        self.update_session_activity(session_id)

        try:
            if request.method == "initialize":
                return await self._handle_initialize(session, request)
            elif request.method == "initialized":
                return await self._handle_initialized(session, request)
            elif request.method == "tools/list":
                return await self._handle_list_tools(session, request)
            elif request.method == "tools/call":
                return await self._handle_tool_call(session, request)
            elif request.method == "resources/list":
                return await self._handle_list_resources(session, request)
            elif request.method == "resources/read":
                return await self._handle_resource_read(session, request)
            elif request.method == "ping":
                return MCPResponse(id=request.id, result={})
            else:
                return MCPResponse(
                    id=request.id,
                    error=MCPError(code=-32601, message=f"Method not found: {request.method}"),
                )
        except Exception as e:
            return MCPResponse(
                id=request.id,
                error=MCPError(code=-32603, message=f"Internal error: {str(e)}"),
            )

    async def _handle_initialize(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle initialize request."""
        params = InitializeParams(**(request.params or {}))
        session.initialized = True
        session.capabilities = params.capabilities
        session.protocol_version = params.protocolVersion

        result = InitializeResult(
            protocolVersion=SchemaVersion.latest(),
            capabilities={
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
                "logging": {},
            },
            serverInfo={
                "name": "contextforge-mcp",
                "version": "0.1.0",
            },
            instructions="ContextForge MCP Gateway - Enterprise RAG Pipeline",
        )
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_initialized(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle initialized notification."""
        # No response for notifications
        return MCPResponse(id=request.id, result={})

    async def _handle_list_tools(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle tools/list request."""
        # Import here to avoid circular imports
        from contextforge.mcp.schema import ALL_TOOLS

        result = ListToolsResult(tools=ALL_TOOLS)
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_tool_call(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle tools/call request."""
        params = ToolCallParams(**(request.params or {}))
        # This will be overridden by the gateway with actual tool handlers
        result = ToolCallResult(
            content=[{"type": "text", "text": f"Tool {params.name} not implemented"}],
            isError=True,
        )
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_list_resources(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle resources/list request."""
        from contextforge.mcp.schema import ALL_RESOURCES

        result = ListResourcesResult(resources=ALL_RESOURCES)
        return MCPResponse(id=request.id, result=result.model_dump())

    async def _handle_resource_read(self, session: SessionInfo, request: MCPRequest) -> MCPResponse:
        """Handle resources/read request."""
        params = ResourceReadParams(**(request.params or {}))
        result = ResourceReadResult(
            contents=[{"uri": params.uri, "mimeType": "application/json", "text": "Not implemented"}]
        )
        return MCPResponse(id=request.id, result=result.model_dump())


class SSETransport(TransportBase):
    """
    Server-Sent Events transport for MCP.

    Provides real-time bidirectional communication over HTTP.
    """

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        self._event_sources: dict[str, asyncio.Queue] = {}

    async def handle_request(self, request: Request, session_id: str | None) -> Response:
        """Handle SSE connection request."""
        if request.method == "GET":
            return await self._handle_sse_get(request, session_id)
        elif request.method == "POST":
            return await self._handle_sse_post(request, session_id)
        else:
            return Response(status_code=405, content="Method not allowed")

    async def _handle_sse_get(self, request: Request, session_id: str | None) -> StreamingResponse:
        """Handle SSE GET request (event stream)."""
        # Create or get session
        if not session_id:
            session = self.create_session(
                client_id=request.headers.get("X-Client-ID", "anonymous"),
                transport_type=TransportType.SSE,
            )
            session_id = session.session_id
        else:
            session = self.get_session(session_id)
            if not session:
                session = self.create_session(
                    client_id=request.headers.get("X-Client-ID", "anonymous"),
                    transport_type=TransportType.SSE,
                )

        # Create event queue for this connection
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._event_sources[session_id] = event_queue

        async def event_generator() -> AsyncIterator[str]:
            try:
                # Send initial connection event
                yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"

                # Send heartbeat periodically
                last_heartbeat = asyncio.get_event_loop().time()

                while True:
                    try:  # Wait for events with timeout for heartbeat
                        timeout = self.config.heartbeat_interval_seconds
                        event = await asyncio.wait_for(event_queue.get(), timeout=timeout)
                        yield f"data: {json.dumps(event)}\n\n"
                    except TimeoutError:
                        # Send heartbeat
                        now = asyncio.get_event_loop().time()
                        if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                    except Exception:
                        break
            finally:
                # Cleanup
                self._event_sources.pop(session_id, None)
                await self.close_session(session_id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    async def _handle_sse_post(self, request: Request, session_id: str | None) -> Response:
        """Handle SSE POST request (client messages)."""
        if not session_id:
            return Response(status_code=400, content="Session ID required")

        session = self.get_session(session_id)
        if not session:
            return Response(status_code=404, content="Session not found")

        # Parse request body
        try:
            body = await request.body()
            if len(body) > self.config.max_message_size:
                return Response(status_code=413, content="Message too large")

            message_data = json.loads(body)
            request_msg = MCPRequest(**message_data)
        except json.JSONDecodeError:
            return Response(status_code=400, content="Invalid JSON")
        except Exception as e:
            return Response(status_code=400, content=f"Invalid request: {str(e)}")

        # Handle request
        response = await self._handle_mcp_request(session_id, request_msg)

        # Send response via event queue
        if session_id in self._event_sources:
            await self._event_sources[session_id].put(response.model_dump(exclude_none=True))

        return Response(status_code=202, content="Accepted")

    async def send_message(self, session_id: str, message: MCPMessage) -> bool:
        """Send a message to an SSE session."""
        if session_id in self._event_sources:
            try:
                await self._event_sources[session_id].put(message.model_dump(exclude_none=True))
                return True
            except Exception:
                return False
        return False

    async def close_session(self, session_id: str) -> None:
        """Close SSE session."""
        self._sessions.pop(session_id, None)
        self._message_queues.pop(session_id, None)
        self._event_sources.pop(session_id, None)


class StreamableHTTPTransport(TransportBase):
    """
    Streamable HTTP transport for MCP (MCP 2025-06-18 spec).

    Supports both request-response and server-sent events over a single endpoint.
    """

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        self._stream_connections: dict[str, asyncio.Queue] = {}

    async def handle_request(self, request: Request, session_id: str | None) -> Response:
        """Handle Streamable HTTP request."""
        # Determine if this is a streaming request
        accept = request.headers.get("Accept", "")
        wants_stream = "text/event-stream" in accept

        if request.method == "POST":
            if wants_stream:
                return await self._handle_streaming_post(request, session_id)
            else:
                return await self._handle_regular_post(request, session_id)
        elif request.method == "GET" and wants_stream:
            return await self._handle_streaming_get(request, session_id)
        elif request.method == "DELETE":
            return await self._handle_delete(request, session_id)
        else:
            return Response(status_code=405, content="Method not allowed")

    async def _handle_regular_post(self, request: Request, session_id: str | None) -> Response:
        """Handle regular JSON-RPC POST request."""
        # Create or get session
        if not session_id:
            session = self.create_session(
                client_id=request.headers.get("X-Client-ID", "anonymous"),
                transport_type=TransportType.STREAMABLE_HTTP,
            )
            session_id = session.session_id
        else:
            session = self.get_session(session_id)
            if not session:
                return Response(status_code=404, content="Session not found")

        # Parse request
        try:
            body = await request.body()
            if len(body) > self.config.max_message_size:
                return Response(status_code=413, content="Message too large")

            message_data = json.loads(body)

            # Handle batch requests
            if isinstance(message_data, list):
                responses = []
                for msg_data in message_data:
                    req = MCPRequest(**msg_data)
                    resp = await self._handle_mcp_request(session_id, req)
                    responses.append(resp.model_dump(exclude_none=True))
                return Response(
                    content=json.dumps(responses),
                    media_type="application/json",
                    headers={"Mcp-Session-Id": session_id},
                )
            else:
                request_msg = MCPRequest(**message_data)
                response = await self._handle_mcp_request(session_id, request_msg)
                return Response(
                    content=json.dumps(response.model_dump(exclude_none=True)),
                    media_type="application/json",
                    headers={"Mcp-Session-Id": session_id},
                )
        except json.JSONDecodeError:
            return Response(status_code=400, content="Invalid JSON")
        except Exception as e:
            return Response(status_code=400, content=f"Invalid request: {str(e)}")

    async def _handle_streaming_post(self, request: Request, session_id: str | None) -> StreamingResponse:
        """Handle streaming POST request (client sends messages, server streams responses)."""
        # Create or get session
        if not session_id:
            session = self.create_session(
                client_id=request.headers.get("X-Client-ID", "anonymous"),
                transport_type=TransportType.STREAMABLE_HTTP,
            )
            session_id = session.session_id
        else:
            session = self.get_session(session_id)
            if not session:
                session = self.create_session(
                    client_id=request.headers.get("X-Client-ID", "anonymous"),
                    transport_type=TransportType.STREAMABLE_HTTP,
                )

        # Create response queue for streaming
        response_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._stream_connections[session_id] = response_queue

        async def stream_generator() -> AsyncIterator[str]:
            try:
                # Send initial connection event
                yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"

                # Read request body as stream
                async for chunk in request.stream():
                    if chunk:
                        try:
                            # Parse each line as a separate JSON-RPC request
                            lines = chunk.decode().strip().split("\n")
                            for line in lines:
                                if line.strip():
                                    message_data = json.loads(line)
                                    request_msg = MCPRequest(**message_data)
                                    response = await self._handle_mcp_request(session_id, request_msg)
                                    yield f"data: {json.dumps(response.model_dump(exclude_none=True))}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'error': 'Invalid JSON'})}\n\n"
                        except Exception as e:
                            yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Keep connection alive for server-initiated messages
                last_heartbeat = asyncio.get_event_loop().time()
                while True:
                    try:
                        timeout = self.config.heartbeat_interval_seconds
                        event = await asyncio.wait_for(response_queue.get(), timeout=timeout)
                        yield f"data: {json.dumps(event)}\n\n"
                    except TimeoutError:
                        now = asyncio.get_event_loop().time()
                        if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                    except Exception:
                        break
            finally:
                self._stream_connections.pop(session_id, None)
                await self.close_session(session_id)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Mcp-Session-Id": session_id,
                "X-Accel-Buffering": "no",
            },
        )

    async def _handle_streaming_get(self, request: Request, session_id: str | None) -> StreamingResponse:
        """Handle streaming GET request (server-sent events only)."""
        if not session_id:
            return Response(status_code=400, content="Session ID required")

        session = self.get_session(session_id)
        if not session:
            return Response(status_code=404, content="Session not found")

        # Create response queue for this stream
        response_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        stream_key = f"{session_id}:stream"
        self._stream_connections[stream_key] = response_queue

        async def stream_generator() -> AsyncIterator[str]:
            try:
                yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"

                last_heartbeat = asyncio.get_event_loop().time()
                while True:
                    try:
                        timeout = self.config.heartbeat_interval_seconds
                        event = await asyncio.wait_for(response_queue.get(), timeout=timeout)
                        yield f"data: {json.dumps(event)}\n\n"
                    except TimeoutError:
                        now = asyncio.get_event_loop().time()
                        if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                    except Exception:
                        break
            finally:
                self._stream_connections.pop(stream_key, None)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Mcp-Session-Id": session_id,
                "X-Accel-Buffering": "no",
            },
        )

    async def _handle_delete(self, request: Request, session_id: str | None) -> Response:
        """Handle DELETE request to close session."""
        if not session_id:
            return Response(status_code=400, content="Session ID required")

        await self.close_session(session_id)
        return Response(status_code=204)

    async def send_message(self, session_id: str, message: MCPMessage) -> bool:
        """Send a message to a Streamable HTTP session."""
        # Try direct stream connection first
        stream_key = f"{session_id}:stream"
        if stream_key in self._stream_connections:
            try:
                await self._stream_connections[stream_key].put(message.model_dump(exclude_none=True))
                return True
            except Exception:
                pass

        # Try main stream connection
        if session_id in self._stream_connections:
            try:
                await self._stream_connections[session_id].put(message.model_dump(exclude_none=True))
                return True
            except Exception:
                pass

        return False

    async def close_session(self, session_id: str) -> None:
        """Close Streamable HTTP session."""
        self._sessions.pop(session_id, None)
        self._message_queues.pop(session_id, None)
        self._stream_connections.pop(session_id, None)
        self._stream_connections.pop(f"{session_id}:stream", None)


class WebSocketTransport(TransportBase):
    """
    WebSocket transport for MCP (future use).

    Provides full-duplex communication over WebSocket.
    """

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        self._websockets: dict[str, WebSocket] = {}

    async def handle_request(self, request: Request, session_id: str | None) -> Response:
        """WebSocket upgrade handled separately."""
        return Response(status_code=501, content="WebSocket transport not yet implemented")

    async def handle_websocket(self, websocket: WebSocket, session_id: str | None) -> None:
        """Handle WebSocket connection."""
        await websocket.accept()

        if not session_id:
            session = self.create_session(
                client_id="anonymous",
                transport_type=TransportType.WEBSOCKET,
            )
            session_id = session.session_id
        else:
            session = self.get_session(session_id)
            if not session:
                session = self.create_session(
                    client_id="anonymous",
                    transport_type=TransportType.WEBSOCKET,
                )

        self._websockets[session_id] = websocket

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message_data = json.loads(data)
                    request_msg = MCPRequest(**message_data)
                    response = await self._handle_mcp_request(session_id, request_msg)
                    await websocket.send_text(json.dumps(response.model_dump(exclude_none=True)))
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                except Exception as e:
                    await websocket.send_text(json.dumps({"error": str(e)}))
        except Exception:
            pass
        finally:
            self._websockets.pop(session_id, None)
            await self.close_session(session_id)

    async def send_message(self, session_id: str, message: MCPMessage) -> bool:
        """Send a message to a WebSocket session."""
        if session_id in self._websockets:
            try:
                await self._websockets[session_id].send_text(json.dumps(message.model_dump(exclude_none=True)))
                return True
            except Exception:
                return False
        return False

    async def close_session(self, session_id: str) -> None:
        """Close WebSocket session."""
        if session_id in self._websockets:
            try:
                await self._websockets[session_id].close()
            except Exception:
                pass
            self._websockets.pop(session_id, None)
        self._sessions.pop(session_id, None)
        self._message_queues.pop(session_id, None)


# Transport factory
def create_transport(transport_type: TransportType, config: TransportConfig | None = None) -> TransportBase:
    """Create transport instance by type."""
    config = config or TransportConfig(type=transport_type)

    if transport_type == TransportType.SSE:
        return SSETransport(config)
    elif transport_type == TransportType.STREAMABLE_HTTP:
        return StreamableHTTPTransport(config)
    elif transport_type == TransportType.WEBSOCKET:
        return WebSocketTransport(config)
    else:
        raise ValueError(f"Unknown transport type: {transport_type}")


# Default transport instances
_default_transport_config = TransportConfig()
_sse_transport = SSETransport(_default_transport_config)
_streamable_transport = StreamableHTTPTransport(_default_transport_config)


def get_sse_transport() -> SSETransport:
    return _sse_transport


def get_streamable_transport() -> StreamableHTTPTransport:
    return _streamable_transport
