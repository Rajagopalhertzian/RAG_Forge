"""
ContextForge Base Indexer

Abstract base class for vector indexers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


@dataclass
class VectorRecord:
    """A vector record for indexing."""

    id: UUID
    embedding: list[float]
    metadata: dict[str, Any]
    document_id: UUID | None = None
    chunk_index: int | None = None


class IndexerConfig(BaseModel):
    """Base configuration for indexers."""

    dimensions: int = Field(default=1024, ge=1, le=8192)
    batch_size: int = Field(default=100, ge=1, le=10000)


class BaseIndexer(ABC):
    """Abstract base class for vector indexers."""

    def __init__(self, config: IndexerConfig):
        self.config = config

    @property
    @abstractmethod
    def indexer_name(self) -> str:
        """Return the indexer name."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the indexer."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the indexer."""
        pass

    @abstractmethod
    async def upsert(self, records: list[VectorRecord]) -> int:
        """Insert or update vectors."""
        pass

    @abstractmethod
    async def delete(self, ids: list[UUID]) -> int:
        """Delete vectors by IDs."""
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        """Search for similar vectors."""
        pass

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get indexer statistics."""
        pass


class IndexerRegistry:
    """Registry for managing indexer instances."""

    _indexers: dict[str, type[BaseIndexer]] = {}

    @classmethod
    def register(cls, indexer_class: type[BaseIndexer]) -> type[BaseIndexer]:
        """Register an indexer class."""
        # Use class attribute instead of instantiating
        indexer_name = getattr(indexer_class, 'indexer_name', None)

        if indexer_name:
            cls._indexers[indexer_name] = indexer_class
        return indexer_class

    @classmethod
    def get(cls, name: str) -> type[BaseIndexer] | None:
        """Get indexer class by name."""
        return cls._indexers.get(name)

    @classmethod
    def get_instance(cls, name: str, config: IndexerConfig | None = None) -> BaseIndexer | None:
        """Get indexer instance by name."""
        indexer_class = cls.get(name)
        if indexer_class:
            return indexer_class(config)
        return None

    @classmethod
    def list_indexers(cls) -> list[str]:
        """List all registered indexers."""
        return list(cls._indexers.keys())
