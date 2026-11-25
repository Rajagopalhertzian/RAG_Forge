"""
ContextForge Base Chunker

Abstract base class for chunking strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class Chunk:
    """Represents a document chunk."""

    content: str
    index: int
    token_count: int
    metadata: dict[str, Any]
    start_char: int | None = None
    end_char: int | None = None


class ChunkerConfig(BaseModel):
    """Base configuration for chunkers."""

    chunk_size: int = Field(default=512, ge=100, le=8192)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)
    min_chunk_size: int = Field(default=50, ge=10, le=1000)


class BaseChunker(ABC):
    """Abstract base class for document chunkers."""

    def __init__(self, config: ChunkerConfig | None = None):
        self.config = config or ChunkerConfig()

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Return the strategy name."""
        pass

    @abstractmethod
    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunk the input text."""
        pass

    def _count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (approximate)."""
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            # Fallback: rough approximation
            return len(text) // 4

    def _merge_metadata(self, base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        """Merge metadata dictionaries."""
        merged = base.copy()
        merged.update(extra)
        return merged


class ChunkerRegistry:
    """Registry for managing chunker instances."""

    _chunkers: dict[str, type[BaseChunker]] = {}

    @classmethod
    def register(cls, chunker_class: type[BaseChunker]) -> type[BaseChunker]:
        """Register a chunker class."""
        instance = chunker_class()
        cls._chunkers[instance.strategy_name] = chunker_class
        return chunker_class

    @classmethod
    def get(cls, strategy: str) -> type[BaseChunker] | None:
        """Get chunker class by strategy name."""
        return cls._chunkers.get(strategy)

    @classmethod
    def get_instance(cls, strategy: str, config: ChunkerConfig | None = None) -> BaseChunker | None:
        """Get chunker instance by strategy name."""
        chunker_class = cls.get(strategy)
        if chunker_class:
            return chunker_class(config)
        return None

    @classmethod
    def list_strategies(cls) -> list[str]:
        """List all registered strategies."""
        return list(cls._chunkers.keys())
