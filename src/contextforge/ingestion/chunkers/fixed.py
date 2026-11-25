"""
ContextForge Fixed Chunker

Recursive character-based chunking with configurable separators.
"""

from __future__ import annotations

from typing import Any

from contextforge.ingestion.chunkers.base import BaseChunker, Chunk, ChunkerConfig, ChunkerRegistry


class FixedChunkerConfig(ChunkerConfig):
    """Configuration for fixed chunker."""

    separators: list[str] = [
        "\n\n",
        "\n",
        ". ",
        "! ",
        "? ",
        "; ",
        ": ",
        ", ",
        " ",
        "",
    ]
    keep_separator: bool = True


@ChunkerRegistry.register
class FixedChunker(BaseChunker):
    """Fixed-size chunker using recursive character splitting."""

    strategy_name = "fixed"

    def __init__(self, config: FixedChunkerConfig | None = None):
        super().__init__(config or FixedChunkerConfig())

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunk text using recursive character splitting."""
        if not text.strip():
            return []

        separators = self.config.separators
        chunks = self._split_text(text, separators)

        # Post-process to ensure chunk sizes
        final_chunks = []
        for chunk_text in chunks:
            if self._count_tokens(chunk_text) <= self.config.chunk_size:
                final_chunks.append(chunk_text)
            else:
                # Further split oversized chunks
                final_chunks.extend(self._split_oversized(chunk_text))

        # Create Chunk objects with metadata
        result = []
        char_offset = 0
        for i, chunk_text in enumerate(final_chunks):
            token_count = self._count_tokens(chunk_text)
            start_char = text.find(chunk_text, char_offset)
            if start_char == -1:
                start_char = char_offset
            end_char = start_char + len(chunk_text)
            char_offset = end_char

            chunk_metadata = self._merge_metadata(metadata or {}, {
                "strategy": self.strategy_name,
                "chunk_size": self.config.chunk_size,
                "chunk_overlap": self.config.chunk_overlap,
            })

            result.append(Chunk(
                content=chunk_text,
                index=i,
                token_count=token_count,
                metadata=chunk_metadata,
                start_char=start_char,
                end_char=end_char,
            ))

        return result

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text by separators."""
        if not separators:
            return [text]

        separator = separators[0]
        remaining_separators = separators[1:]

        if separator == "":
            # Character-level split
            return list(text)

        splits = text.split(separator)
        if len(splits) == 1:
            # No splits found, try next separator
            return self._split_text(text, remaining_separators)

        # Rejoin with separator if keep_separator
        if self.config.keep_separator:
            result = []
            for i, split in enumerate(splits):
                if i > 0:
                    result.append(separator + split)
                else:
                    result.append(split)
            splits = result

        # Recursively split each part if too large
        final_splits = []
        for split in splits:
            if self._count_tokens(split) <= self.config.chunk_size:
                final_splits.append(split)
            else:
                final_splits.extend(self._split_text(split, remaining_separators))

        return self._merge_splits(final_splits)

    def _split_oversized(self, text: str) -> list[str]:
        """Split oversized chunk by characters."""
        chunk_size = self.config.chunk_size * 4  # Approximate chars
        overlap = self.config.chunk_overlap * 4

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start += chunk_size - overlap

        return chunks

    def _merge_splits(self, splits: list[str]) -> list[str]:
        """Merge small splits to meet minimum size."""
        if not splits:
            return []

        merged = []
        current = splits[0]
        current_tokens = self._count_tokens(current)

        for split in splits[1:]:
            split_tokens = self._count_tokens(split)

            if current_tokens + split_tokens <= self.config.chunk_size:
                current += split
                current_tokens += split_tokens
            else:
                if current_tokens >= self.config.min_chunk_size:
                    merged.append(current)
                else:
                    # Too small, try to merge with next anyway
                    merged.append(current)
                current = split
                current_tokens = split_tokens

        if current_tokens >= self.config.min_chunk_size or not merged:
            merged.append(current)

        return merged
