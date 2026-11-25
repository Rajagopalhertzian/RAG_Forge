"""
ContextForge Test Configuration

Pytest configuration and fixtures.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set test environment variables
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/contextforge_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("VECTOR_STORE", "faiss")
os.environ.setdefault("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
os.environ.setdefault("LOCAL_EMBEDDING_DIMENSIONS", "384")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


# =============================================================================
# Event Loop
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create database engine for tests."""
    from contextforge.storage.database import close_db, engine, init_db

    await init_db()
    yield engine
    await close_db()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create database session for tests."""
    from contextforge.storage.database import async_session_maker

    async with async_session_maker() as session:
        yield session
        await session.rollback()


# =============================================================================
# Repository Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def document_repo(db_session):
    """Document repository fixture."""
    from contextforge.storage.repositories import DocumentRepository
    return DocumentRepository(db_session)


@pytest_asyncio.fixture
async def chunk_repo(db_session):
    """Chunk repository fixture."""
    from contextforge.storage.repositories import ChunkRepository
    return ChunkRepository(db_session)


@pytest_asyncio.fixture
async def job_repo(db_session):
    """Ingestion job repository fixture."""
    from contextforge.storage.repositories import IngestionJobRepository
    return IngestionJobRepository(db_session)


# =============================================================================
# Pipeline Fixtures
# =============================================================================

@pytest.fixture
def ingestion_pipeline():
    """Create ingestion pipeline for tests."""
    from contextforge.ingestion import IngestionPipeline

    pipeline = IngestionPipeline.from_config(
        source_type="markdown",
        strategy="fixed",
        embedding_provider="local",
        vector_store="faiss",
    )

    yield pipeline


# =============================================================================
# Utility Fixtures
# =============================================================================

@pytest.fixture
def sample_documents():
    """Sample documents for testing."""
    return [
        "This is a test document about machine learning and artificial intelligence.",
        "Another document discussing deep learning techniques and neural networks.",
        "A third text about natural language processing and transformers.",
        "Short text.",
        "A much longer document that contains multiple sentences and covers various topics in artificial intelligence including neural networks, transformers, and attention mechanisms.",
    ]


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "eval: Evaluation tests (slow)")
    config.addinivalue_line("markers", "slow: Slow tests")


# =============================================================================
# Async Test Support
# =============================================================================

@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio tests."""
    return "asyncio"
