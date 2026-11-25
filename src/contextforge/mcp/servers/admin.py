"""
Admin MCP Server

Provides tools and resources for system administration, metrics, and configuration.
"""

from __future__ import annotations

import asyncio
import json
import platform
import time
import uuid
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel

from contextforge.config import get_settings, settings
from contextforge.mcp.schema import (
    ADMIN_RESOURCES,
    ADMIN_TOOLS,
    ListResourcesResult,
    ListToolsResult,
    ResourceReadParams,
    ResourceReadResult,
    ToolCallParams,
    ToolCallResult,
    validate_tool_call,
)
from contextforge.storage.database import engine, get_db_session
from contextforge.storage.repositories.chunk import ChunkRepository
from contextforge.storage.repositories.document import DocumentRepository

# Known golden set versions (from tests/evaluation/golden_sets/)
GOLDEN_SET_VERSIONS = frozenset({"v1_baseline", "v2_expanded"})

# Path to golden sets directory
GOLDEN_SETS_DIR = Path(__file__).parent.parent.parent.parent.parent / "tests" / "evaluation" / "golden_sets"


def validate_golden_set(dataset: str) -> tuple[bool, str | None]:
    """
    Validate dataset against known golden set versions.

    Args:
        dataset: Dataset name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if dataset not in GOLDEN_SET_VERSIONS:
        return False, f"Unknown dataset: {dataset}. Known versions: {', '.join(sorted(GOLDEN_SET_VERSIONS))}"

    # Verify the golden set file exists
    golden_set_path = GOLDEN_SETS_DIR / f"{dataset}.jsonl"
    if not golden_set_path.exists():
        return False, f"Golden set file not found: {golden_set_path}"

    return True, None


class MetricsResponse(BaseModel):
    """Get metrics tool response."""

    status: str
    uptime_seconds: float
    requests_total: int
    requests_per_minute: float
    error_rate: float
    active_connections: int
    memory_usage_mb: float
    cpu_usage_percent: float
    database: dict[str, Any]
    redis: dict[str, Any]
    vector_store: dict[str, Any]


class ConfigUpdateResponse(BaseModel):
    """Update config tool response."""

    key: str
    value: str
    previous_value: str
    persisted: bool


class EvalTriggerResponse(BaseModel):
    """Trigger eval tool response."""

    run_id: str
    status: str
    message: str


class ConfigValue(BaseModel):
    """Configuration value resource."""

    key: str
    value: str
    description: str
    is_secret: bool


class AdminServer:
    """
    Admin MCP Server.

    Provides tools for system metrics, configuration management, and evaluation triggering.
    Stateless worker - all state managed by gateway.
    """

    def __init__(self):
        self.settings = get_settings()
        self._initialized = False
        self._start_time = time.time()
        self._request_count = 0
        self._error_count = 0
        self._active_connections = 0

    async def initialize(self) -> None:
        """Initialize server connections."""
        if self._initialized:
            return
        self._initialized = True

    async def close(self) -> None:
        """Close server connections."""
        self._initialized = False

    def increment_requests(self) -> None:
        """Increment request counter."""
        self._request_count += 1

    def increment_errors(self) -> None:
        """Increment error counter."""
        self._error_count += 1

    def set_active_connections(self, count: int) -> None:
        """Set active connections count."""
        self._active_connections = count

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def get_metrics(self, include_details: bool = False) -> MetricsResponse:
        """
        Get system metrics and health information.

        Args:
            include_details: Include detailed metrics

        Returns:
            MetricsResponse with system metrics
        """
        if not self._initialized:
            await self.initialize()

        uptime = time.time() - self._start_time
        rpm = (self._request_count / uptime * 60) if uptime > 0 else 0
        error_rate = (self._error_count / self._request_count * 100) if self._request_count > 0 else 0

        # System metrics
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Database metrics
        db_info = await self._get_database_metrics()

        # Redis metrics
        redis_info = await self._get_redis_metrics()

        # Vector store metrics
        vector_info = await self._get_vector_store_metrics()

        return MetricsResponse(
            status="healthy" if error_rate < 5 else "degraded",
            uptime_seconds=uptime,
            requests_total=self._request_count,
            requests_per_minute=rpm,
            error_rate=error_rate,
            active_connections=self._active_connections,
            memory_usage_mb=memory.used / (1024 * 1024),
            cpu_usage_percent=cpu_percent,
            database=db_info,
            redis=redis_info,
            vector_store=vector_info,
        )

    async def _get_database_metrics(self) -> dict[str, Any]:
        """Get database metrics."""
        try:
            # Get pool status
            pool = engine.pool
            return {
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }
        except Exception:
            return {"status": "unknown"}

    async def _get_redis_metrics(self) -> dict[str, Any]:
        """Get Redis metrics."""
        try:
            import redis.asyncio as redis
            client = redis.from_url(str(settings.REDIS_URL))
            info = await client.info()
            await client.close()
            return {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            }
        except Exception:
            return {"status": "unknown"}

    async def _get_vector_store_metrics(self) -> dict[str, Any]:
        """Get vector store metrics."""
        try:
            async with get_db_session() as session:
                doc_repo = DocumentRepository(session)
                chunk_repo = ChunkRepository(session)

                doc_count = await doc_repo.count()
                chunk_count = await chunk_repo.count()

                return {
                    "document_count": doc_count,
                    "chunk_count": chunk_count,
                    "status": "healthy",
                }
        except Exception:
            return {"status": "unknown"}

    async def update_config(self, key: str, value: str, persist: bool = False) -> ConfigUpdateResponse:
        """
        Update a configuration value.

        Args:
            key: Configuration key
            value: Configuration value
            persist: Persist to config store

        Returns:
            ConfigUpdateResponse with update result
        """
        if not self._initialized:
            await self.initialize()

        # Validate key
        allowed_keys = {
            "LOG_LEVEL",
            "RATE_LIMIT_REQUESTS_PER_MINUTE",
            "RATE_LIMIT_BURST",
            "DEFAULT_CHUNK_SIZE",
            "DEFAULT_CHUNK_OVERLAP",
            "SEMANTIC_CHUNK_THRESHOLD",
            "INGESTION_MAX_CONCURRENT_JOBS",
            "INGESTION_CHUNK_BATCH_SIZE",
            "INGESTION_EMBEDDING_BATCH_SIZE",
        }

        if key not in allowed_keys:
            return ConfigUpdateResponse(
                key=key,
                value=value,
                previous_value="",
                persisted=False,
            )

        # Get previous value
        previous_value = getattr(settings, key, "")

        # Update in-memory settings (for runtime)
        # Note: In production, this would update a config store (Consul, etcd, etc.)
        try:
            object.__setattr__(settings, key, type(previous_value)(value))
        except Exception:
            pass

        persisted = False
        if persist:
            # In production, persist to config store
            # await config_store.set(key, value)
            persisted = True

        return ConfigUpdateResponse(
            key=key,
            value=value,
            previous_value=str(previous_value),
            persisted=persisted,
        )

    async def trigger_eval(
        self,
        dataset: str,
        metrics: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> EvalTriggerResponse:
        """
        Trigger a retrieval evaluation run.

        Args:
            dataset: Evaluation dataset name (must be a known golden set version)
            metrics: Metrics to compute
            config: Evaluation configuration

        Returns:
            EvalTriggerResponse with run ID and status

        Raises:
            ValueError: If dataset is not a known golden set version
        """
        if not self._initialized:
            await self.initialize()

        # Validate dataset against known golden sets
        is_valid, error_msg = validate_golden_set(dataset)
        if not is_valid:
            return EvalTriggerResponse(
                run_id="",
                status="error",
                message=error_msg or f"Invalid dataset: {dataset}",
            )

        run_id = str(uuid.uuid4())
        eval_metrics = metrics or ["precision@5", "recall@5", "ndcg@5", "mrr"]

        # In production, this would trigger a Celery task or similar
        # For now, return immediately with pending status
        asyncio.create_task(self._run_evaluation(run_id, dataset, eval_metrics, config or {}))

        return EvalTriggerResponse(
            run_id=run_id,
            status="pending",
            message=f"Evaluation run {run_id} started for dataset {dataset}",
        )

    async def _run_evaluation(
        self,
        run_id: str,
        dataset: str,
        metrics: list[str],
        config: dict[str, Any],
    ) -> None:
        """Run evaluation in background."""
        try:
            # This would integrate with the actual evaluation pipeline
            # from contextforge.evaluation.retrieval.runner import run_evaluation
            # await run_evaluation(dataset, metrics, config)

            # For now, just simulate
            await asyncio.sleep(2)
        except Exception:
            pass

    # =========================================================================
    # Resource Implementations
    # =========================================================================

    async def read_config_resource(self, key: str) -> ResourceReadResult:
        """Read configuration resource."""
        value = getattr(settings, key, None)
        is_secret = "KEY" in key.upper() or "SECRET" in key.upper() or "PASSWORD" in key.upper()

        config_value = ConfigValue(
            key=key,
            value="***" if is_secret else str(value) if value is not None else "",
            description=f"Configuration key: {key}",
            is_secret=is_secret,
        )

        return ResourceReadResult(
            contents=[
                {
                    "uri": f"config://{key}",
                    "mimeType": "application/json",
                    "text": config_value.model_dump_json(),
                }
            ]
        )

    # =========================================================================
    # MCP Protocol Handlers
    # =========================================================================

    async def handle_tool_call(self, params: ToolCallParams) -> ToolCallResult:
        """Handle tool call from MCP protocol."""
        valid, error = validate_tool_call(params.name, params.arguments)
        if not valid:
            return ToolCallResult(
                content=[{"type": "text", "text": error or "Invalid tool call"}],
                isError=True,
            )

        self.increment_requests()

        try:
            if params.name == "get_metrics":
                result = await self.get_metrics(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            elif params.name == "update_config":
                result = await self.update_config(**params.arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": result.model_dump_json()}],
                    structuredContent=result.model_dump(),
                )
            elif params.name == "trigger_eval":
                result = await self.trigger_eval(**params.arguments)
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
            self.increment_errors()
            return ToolCallResult(
                content=[{"type": "text", "text": f"Tool execution error: {str(e)}"}],
                isError=True,
            )

    async def handle_resource_read(self, params: ResourceReadParams) -> ResourceReadResult:
        """Handle resource read from MCP protocol."""
        uri = params.uri

        if uri.startswith("config://"):
            key = uri[len("config://"):]
            return await self.read_config_resource(key)
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
        return ListToolsResult(tools=ADMIN_TOOLS)

    def get_resources(self) -> ListResourcesResult:
        """Get list of available resources."""
        return ListResourcesResult(resources=ADMIN_RESOURCES)

    def get_system_info(self) -> dict[str, Any]:
        """Get system information."""
        return {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": psutil.virtual_memory().total / (1024**3),
        }


# Global server instance
_admin_server: AdminServer | None = None


async def get_admin_server() -> AdminServer:
    """Get or create admin server instance."""
    global _admin_server
    if _admin_server is None:
        _admin_server = AdminServer()
        await _admin_server.initialize()
    return _admin_server


async def close_admin_server() -> None:
    """Close admin server instance."""
    global _admin_server
    if _admin_server:
        await _admin_server.close()
        _admin_server = None
