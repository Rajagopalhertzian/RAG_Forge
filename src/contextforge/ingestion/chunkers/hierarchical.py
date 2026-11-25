"""
ContextForge Hierarchical Chunker

Parent-child chunking strategy for multi-granularity retrieval.
"""

from __future__ import annotations

from typing import Any

from contextforge.ingestion.chunkers.base import BaseChunker, Chunk, ChunkerConfig, ChunkerRegistry
from contextforge.ingestion.chunkers.fixed import FixedChunker, FixedChunkerConfig


class HierarchicalChunkerConfig(ChunkerConfig):
    """Configuration for hierarchical chunker."""

    parent_chunk_size: int = 1024
    parent_chunk_overlap: int = 100
    child_chunk_size: int = 256
    child_chunk_overlap: int = 25
    min_parent_chars: int = 200


@ChunkerRegistry.register
class HierarchicalChunker(BaseChunker):
    """Hierarchical chunker creating parent-child relationships."""

    strategy_name = "hierarchical"

    def __init__(self, config: HierarchicalChunkerConfig | None = None):
        super().__init__(config or HierarchicalChunkerConfig())

        # Parent chunker (larger chunks)
        self.parent_chunker = FixedChunker(FixedChunkerConfig(
            chunk_size=self.config.parent_chunk_size,
            chunk_overlap=self.config.parent_chunk_overlap,
        ))

        # Child chunker (smaller chunks)
        self.child_chunker = FixedChunker(FixedChunkerConfig(
            chunk_size=self.config.child_chunk_size,
            chunk_overlap=self.config.child_chunk_overlap,
        ))

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Create hierarchical parent-child chunks."""
        if not text.strip():
            return []

        # First, create parent chunks
        parent_chunks = self.parent_chunker.chunk(text, metadata)

        # For each parent, create child chunks
        all_chunks = []
        child_index = 0

        for parent_idx, parent_chunk in enumerate(parent_chunks):
            # Add parent chunk with hierarchical metadata
            parent_metadata = self._merge_metadata(parent_chunk.metadata, {
                "strategy": self.strategy_name,
                "hierarchy_level": "parent",
                "parent_index": parent_idx,
                "child_indices": [],
            })

            parent_chunk.metadata = parent_metadata
            parent_chunk.index = len(all_chunks)
            all_chunks.append(parent_chunk)

            # Create child chunks from parent content
            child_chunks = self.child_chunker.chunk(parent_chunk.content, metadata)

            # Update child metadata with parent reference
            child_indices = []
            for child_chunk in child_chunks:
                child_metadata = self._merge_metadata(child_chunk.metadata, {
                    "strategy": self.strategy_name,
                    "hierarchy_level": "child",
                    "parent_index": parent_idx,
                    "parent_chunk_id": f"parent_{parent_idx}",
                })
                child_chunk.metadata = child_metadata
                child_chunk.index = len(all_chunks)
                child_indices.append(child_chunk.index)
                all_chunks.append(child_chunk)

            # Update parent with child indices
            all_chunks[parent_idx].metadata["child_indices"] = child_indices

        # Re-index all chunks
        for i, chunk in enumerate(all_chunks):
            chunk.index = i

        return all_chunks

    def get_parent_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Extract only parent chunks."""
        return [c for c in chunks if c.metadata.get("hierarchy_level") == "parent"]

    def get_child_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Extract only child chunks."""
        return [c for c in chunks if c.metadata.get("hierarchy_level") == "child"]

    def get_children_for_parent(self, chunks: list[Chunk], parent_index: int) -> list[Chunk]:
        """Get all child chunks for a given parent."""
        parent_chunk = next((c for c in chunks if c.index == parent_index), None)
        if not parent_chunk:
            return []

        child_indices = parent_chunk.metadata.get("child_indices", [])
        return [c for c in chunks if c.index in child_indices]
