"""
ContextForge Base Loader

Abstract base class for document loaders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class DocumentContent:
    """Represents loaded document content."""

    content: str
    metadata: dict[str, Any]
    source_id: str
    title: str | None = None


class LoaderConfig(BaseModel):
    """Base configuration for loaders."""

    max_file_size_mb: int = Field(default=100, ge=1, le=1000)
    encoding: str = "utf-8"
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class BaseLoader(ABC):
    """Abstract base class for document loaders."""

    def __init__(self, config: LoaderConfig | None = None):
        self.config = config or LoaderConfig()

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source type identifier (e.g., 'pdf', 'notion', 'github')."""
        pass

    @abstractmethod
    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single document by source ID."""
        pass

    @abstractmethod
    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple documents."""
        pass

    @abstractmethod
    async def validate_source(self, source_id: str) -> bool:
        """Validate that a source exists and is accessible."""
        pass

    def _create_metadata(self, **extra: Any) -> dict[str, Any]:
        """Create metadata dict with source info and extra fields."""
        metadata = {
            "source_type": self.source_type,
            **self.config.extra_metadata,
            **extra,
        }
        return metadata


class LoaderRegistry:
    """Registry for managing loader instances."""

    _loaders: dict[str, type[BaseLoader]] = {}

    @classmethod
    def register(cls, loader_class: type[BaseLoader]) -> type[BaseLoader]:
        """Register a loader class."""
        instance = loader_class()
        cls._loaders[instance.source_type] = loader_class
        return loader_class

    @classmethod
    def get(cls, source_type: str) -> type[BaseLoader] | None:
        """Get loader class by source type."""
        return cls._loaders.get(source_type)

    @classmethod
    def get_instance(cls, source_type: str, config: LoaderConfig | None = None) -> BaseLoader | None:
        """Get loader instance by source type."""
        loader_class = cls.get(source_type)
        if loader_class:
            return loader_class(config)
        return None

    @classmethod
    def list_sources(cls) -> list[str]:
        """List all registered source types."""
        return list(cls._loaders.keys())
