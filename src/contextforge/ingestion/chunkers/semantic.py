"""
ContextForge Semantic Chunker

Semantic chunking using embedding similarity to detect boundaries.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from contextforge.ingestion.chunkers.base import BaseChunker, Chunk, ChunkerConfig, ChunkerRegistry
from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderConfig, EmbedderRegistry


class SemanticChunkerConfig(ChunkerConfig):
    """Configuration for semantic chunker."""

    threshold: float = 0.7
    min_sentences: int = 1
    max_sentences: int = 20
    embedding_model: str = "BAAI/bge-m3"  # Use local embedder for boundary detection
    buffer_size: int = 1  # Number of sentences to look ahead/behind


@ChunkerRegistry.register
class SemanticChunker(BaseChunker):
    """Semantic chunker using embedding similarity."""

    strategy_name = "semantic"

    def __init__(self, config: SemanticChunkerConfig | None = None):
        super().__init__(config or SemanticChunkerConfig())
        self._embedder: BaseEmbedder | None = None

    @property
    def embedder(self) -> BaseEmbedder:
        """Get or create embedder for boundary detection."""
        if self._embedder is None:
            embedder_config = EmbedderConfig(
                model_name=self.config.embedding_model,
                batch_size=32,
            )
            self._embedder = EmbedderRegistry.get_instance(
                self.config.embedding_model,
                embedder_config,
            )
            if self._embedder is None:
                # Fallback to local
                from contextforge.ingestion.embedders.local import LocalEmbedder
                self._embedder = LocalEmbedder(embedder_config)
        return self._embedder

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunk text using semantic similarity."""
        if not text.strip():
            return []

        # Split into sentences
        sentences = self._split_sentences(text)
        if len(sentences) <= self.config.min_sentences:
            return [Chunk(
                content=text,
                index=0,
                token_count=self._count_tokens(text),
                metadata=self._merge_metadata(metadata or {}, {"strategy": self.strategy_name}),
            )]

        # Get embeddings for sentences
        embeddings = self.embedder.embed_batch([s["text"] for s in sentences])

        # Find boundaries using similarity
        boundaries = self._find_boundaries(embeddings, sentences)

        # Create chunks from boundaries
        chunks = self._create_chunks(sentences, boundaries, metadata)

        return chunks

    def _split_sentences(self, text: str) -> list[dict[str, Any]]:
        """Split text into sentences with positions."""
        # Simple sentence splitting - in production use spacy or nltk
        import re

        # Split on sentence boundaries
        pattern = r'(?<=[.!?])\s+(?=[A-Z])'
        parts = re.split(pattern, text)

        sentences = []
        char_offset = 0
        for part in parts:
            part = part.strip()
            if part:
                start = text.find(part, char_offset)
                end = start + len(part)
                sentences.append({
                    "text": part,
                    "start_char": start,
                    "end_char": end,
                    "token_count": self._count_tokens(part),
                })
                char_offset = end

        return sentences

    def _find_boundaries(
        self,
        embeddings: list[list[float]],
        sentences: list[dict[str, Any]],
    ) -> list[int]:
        """Find chunk boundaries using embedding similarity."""
        if len(embeddings) < 2:
            return [len(sentences)]

        boundaries = []
        embeddings_array = np.array(embeddings)

        # Compute similarities between adjacent sentences
        for i in range(len(embeddings) - 1):
            # Cosine similarity
            sim = np.dot(embeddings_array[i], embeddings_array[i + 1]) / (
                np.linalg.norm(embeddings_array[i]) * np.linalg.norm(embeddings_array[i + 1])
            )

            # Check buffer zone
            buffer_sim = sim
            for b in range(1, self.config.buffer_size + 1):
                if i + b + 1 < len(embeddings):
                    buf_sim = np.dot(embeddings_array[i], embeddings_array[i + b + 1]) / (
                        np.linalg.norm(embeddings_array[i]) * np.linalg.norm(embeddings_array[i + b + 1])
                    )
                    buffer_sim = min(buffer_sim, buf_sim)

            if buffer_sim < self.config.threshold:
                boundaries.append(i + 1)

        # Always add final boundary
        boundaries.append(len(sentences))

        return boundaries

    def _create_chunks(
        self,
        sentences: list[dict[str, Any]],
        boundaries: list[int],
        metadata: dict[str, Any] | None,
    ) -> list[Chunk]:
        """Create chunks from sentence boundaries."""
        chunks = []
        start_idx = 0

        for i, end_idx in enumerate(boundaries):
            if start_idx >= end_idx:
                continue

            # Get sentences for this chunk
            chunk_sentences = sentences[start_idx:end_idx]
            chunk_text = " ".join(s["text"] for s in chunk_sentences)

            # Check token count
            token_count = self._count_tokens(chunk_text)

            # If too large, split further
            if token_count > self.config.chunk_size:
                sub_chunks = self._split_large_chunk(chunk_sentences, metadata)
                chunks.extend(sub_chunks)
            else:
                chunk_metadata = self._merge_metadata(metadata or {}, {
                    "strategy": self.strategy_name,
                    "threshold": self.config.threshold,
                    "sentence_count": len(chunk_sentences),
                    "start_char": chunk_sentences[0]["start_char"],
                    "end_char": chunk_sentences[-1]["end_char"],
                })

                chunks.append(Chunk(
                    content=chunk_text,
                    index=len(chunks),
                    token_count=token_count,
                    metadata=chunk_metadata,
                    start_char=chunk_sentences[0]["start_char"],
                    end_char=chunk_sentences[-1]["end_char"],
                ))

            start_idx = end_idx

        return chunks

    def _split_large_chunk(
        self,
        sentences: list[dict[str, Any]],
        metadata: dict[str, Any] | None,
    ) -> list[Chunk]:
        """Split a chunk that's too large."""
        # Use fixed chunker as fallback
        from contextforge.ingestion.chunkers.fixed import FixedChunker, FixedChunkerConfig
        fixed_config = FixedChunkerConfig(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        fixed_chunker = FixedChunker(fixed_config)

        text = " ".join(s["text"] for s in sentences)
        fixed_chunks = fixed_chunker.chunk(text, metadata)

        # Update metadata
        for chunk in fixed_chunks:
            chunk.metadata["strategy"] = self.strategy_name
            chunk.metadata["fallback"] = "fixed"

        return fixed_chunks
