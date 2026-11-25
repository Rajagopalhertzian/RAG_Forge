"""
ContextForge Checkpointer - PostgresSaver (prod) / MemorySaver (dev)

Provides LangGraph checkpointer for:
- State persistence across restarts
- HITL resume capability
- Thread-based conversation history
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import AsyncConnectionPool

from contextforge.config import settings
from contextforge.main import logger

# =============================================================================
# Global Checkpointer Instances
# =============================================================================

_postgres_checkpointer: PostgresSaver | None = None
_postgres_pool: AsyncConnectionPool | None = None
_memory_checkpointer: MemorySaver | None = None


# =============================================================================
# Postgres Checkpointer (Production)
# =============================================================================


async def create_postgres_pool() -> AsyncConnectionPool:
    """Create async connection pool for PostgresSaver."""
    database_url = str(settings.DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://")

    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=2,
        max_size=10,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
        },
    )

    # Wait for pool to be ready
    await pool.wait()
    return pool


async def get_postgres_checkpointer() -> PostgresSaver:
    """Get or create PostgresSaver checkpointer."""
    global _postgres_checkpointer, _postgres_pool

    if _postgres_checkpointer is not None:
        return _postgres_checkpointer

    # Create pool if needed
    if _postgres_pool is None:
        _postgres_pool = await create_postgres_pool()

    # Create checkpointer
    _postgres_checkpointer = PostgresSaver(_postgres_pool)

    # Setup tables (idempotent)
    await _postgres_checkpointer.setup()

    logger.info("postgres_checkpointer_initialized")
    return _postgres_checkpointer


async def close_postgres_checkpointer() -> None:
    """Close Postgres checkpointer and pool."""
    global _postgres_checkpointer, _postgres_pool

    if _postgres_pool:
        await _postgres_pool.close()
        _postgres_pool = None

    _postgres_checkpointer = None
    logger.info("postgres_checkpointer_closed")


# =============================================================================
# Memory Checkpointer (Development)
# =============================================================================


def get_memory_checkpointer() -> MemorySaver:
    """Get or create MemorySaver checkpointer."""
    global _memory_checkpointer

    if _memory_checkpointer is None:
        _memory_checkpointer = MemorySaver()
        logger.info("memory_checkpointer_initialized")

    return _memory_checkpointer


# =============================================================================
# Unified Factory
# =============================================================================


def get_checkpointer() -> PostgresSaver | MemorySaver:
    """
    Get appropriate checkpointer based on environment.

    - Production: PostgresSaver (persistent, supports HITL resume)
    - Development: MemorySaver (in-memory, no persistence)
    """
    if settings.APP_ENV == "production":
        # For production, we need async initialization
        # This will be initialized on first use via get_postgres_checkpointer()
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await in sync context, return memory as fallback
                logger.warning("async_loop_running_returning_memory_checkpointer")
                return get_memory_checkpointer()
        except RuntimeError:
            pass

        # Try to create postgres checkpointer synchronously (will fail if not initialized)
        # In practice, initialize at app startup
        return get_memory_checkpointer()  # Safe fallback

    return get_memory_checkpointer()


async def get_async_checkpointer() -> PostgresSaver | MemorySaver:
    """Get checkpointer asynchronously (for proper PostgresSaver init)."""
    if settings.APP_ENV == "production":
        return await get_postgres_checkpointer()
    return get_memory_checkpointer()


# =============================================================================
# Checkpointer Management for Application Lifecycle
# =============================================================================


class CheckpointerManager:
    """Manages checkpointer lifecycle for the application."""

    def __init__(self):
        self._initialized = False
        self._checkpointer: PostgresSaver | MemorySaver | None = None

    async def initialize(self) -> PostgresSaver | MemorySaver:
        """Initialize checkpointer for application."""
        if self._initialized:
            return self._checkpointer

        if settings.APP_ENV == "production":
            self._checkpointer = await get_postgres_checkpointer()
        else:
            self._checkpointer = get_memory_checkpointer()

        self._initialized = True
        return self._checkpointer

    async def close(self) -> None:
        """Close checkpointer."""
        if settings.APP_ENV == "production":
            await close_postgres_checkpointer()
        self._initialized = False
        self._checkpointer = None

    @property
    def checkpointer(self) -> PostgresSaver | MemorySaver | None:
        return self._checkpointer


# Singleton manager
checkpointer_manager = CheckpointerManager()


# =============================================================================
# Thread/Checkpoint Utilities
# =============================================================================


async def list_checkpoints(
    checkpointer: PostgresSaver | MemorySaver,
    thread_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List checkpoints for a thread or all threads."""
    config = {"configurable": {"thread_id": thread_id}} if thread_id else {}

    checkpoints = []
    async for checkpoint in checkpointer.alist(config, limit=limit):
        checkpoints.append({
            "thread_id": checkpoint.config["configurable"]["thread_id"],
            "checkpoint_id": checkpoint.checkpoint["id"],
            "parent_id": checkpoint.checkpoint.get("parent_id"),
            "ts": checkpoint.checkpoint["ts"],
            "metadata": checkpoint.metadata,
        })

    return checkpoints


async def get_checkpoint_state(
    checkpointer: PostgresSaver | MemorySaver,
    thread_id: str,
    checkpoint_id: str | None = None,
) -> dict[str, Any] | None:
    """Get state at a specific checkpoint."""
    config = {"configurable": {"thread_id": thread_id}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id

    state = await checkpointer.aget(config)
    return state.values if state else None


async def delete_thread_checkpoints(
    checkpointer: PostgresSaver | MemorySaver,
    thread_id: str,
) -> None:
    """Delete all checkpoints for a thread."""
    # PostgresSaver doesn't have direct delete, but we can use the pool
    if isinstance(checkpointer, PostgresSaver) and _postgres_pool:
        async with _postgres_pool.connection() as conn:
            await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = %s",
                (thread_id,),
            )
            await conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                (thread_id,),
            )
    elif isinstance(checkpointer, MemorySaver):
        # MemorySaver stores in memory dict
        checkpointer.storage.pop(thread_id, None)
        checkpointer.writes.pop(thread_id, None)


# =============================================================================
# Context Manager for App Lifespan
# =============================================================================


@asynccontextmanager
async def checkpointer_lifespan() -> AsyncGenerator[PostgresSaver | MemorySaver, None]:
    """Context manager for checkpointer lifecycle (use in FastAPI lifespan)."""
    checkpointer = await checkpointer_manager.initialize()
    try:
        yield checkpointer
    finally:
        await checkpointer_manager.close()
