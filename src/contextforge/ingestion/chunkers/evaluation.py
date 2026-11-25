"""
ContextForge Chunking Evaluation

Evaluation metrics for chunking strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class ChunkingMetrics:
    """Metrics for chunking evaluation."""

    # Boundary preservation
    boundary_preservation_score: float = 0.0

    # Semantic coherence
    semantic_coherence: float = 0.0

    # Size distribution
    avg_chunk_size: float = 0.0
    size_std: float = 0.0
    min_chunk_size: int = 0
    max_chunk_size: int = 0

    # Count
    total_chunks: int = 0
    total_tokens: int = 0

    # Overlap
    avg_overlap_ratio: float = 0.0


class ChunkingEvaluator:
    """Evaluates chunking quality using custom metrics."""

    def __init__(self, embedder=None):
        self.embedder = embedder

    def evaluate(
        self,
        original_text: str,
        chunks: list[dict[str, Any]],
        ground_truth_boundaries: list[int] | None = None,
    ) -> ChunkingMetrics:
        """
        Evaluate chunking quality.

        Args:
            original_text: The original text
            chunks: List of chunks with 'content', 'start_char', 'end_char', 'token_count'
            ground_truth_boundaries: Optional ground truth boundary positions
        """
        metrics = ChunkingMetrics()
        metrics.total_chunks = len(chunks)
        metrics.total_tokens = sum(c.get("token_count", 0) for c in chunks)

        if not chunks:
            return metrics

        # Size distribution
        sizes = [c.get("token_count", 0) for c in chunks]
        metrics.avg_chunk_size = np.mean(sizes)
        metrics.size_std = np.std(sizes)
        metrics.min_chunk_size = min(sizes)
        metrics.max_chunk_size = max(sizes)

        # Overlap ratio
        overlap_ratios = []
        for i in range(len(chunks) - 1):
            current_end = chunks[i].get("end_char", 0)
            next_start = chunks[i + 1].get("start_char", 0)
            if current_end > next_start:
                overlap = current_end - next_start
                current_len = current_end - chunks[i].get("start_char", 0)
                if current_len > 0:
                    overlap_ratios.append(overlap / current_len)
        metrics.avg_overlap_ratio = np.mean(overlap_ratios) if overlap_ratios else 0.0

        # Boundary preservation (if ground truth provided)
        if ground_truth_boundaries:
            metrics.boundary_preservation_score = self._compute_boundary_preservation(
                chunks, ground_truth_boundaries
            )

        # Semantic coherence (if embedder available)
        if self.embedder and len(chunks) > 1:
            metrics.semantic_coherence = self._compute_semantic_coherence(chunks)

        return metrics

    def _compute_boundary_preservation(
        self,
        chunks: list[dict[str, Any]],
        ground_truth: list[int],
    ) -> float:
        """
        Compute boundary preservation score.

        Measures how well chunk boundaries align with ground truth boundaries.
        """
        if not ground_truth or not chunks:
            return 0.0

        chunk_boundaries = set()
        for chunk in chunks:
            start = chunk.get("start_char", 0)
            end = chunk.get("end_char", 0)
            chunk_boundaries.add(start)
            chunk_boundaries.add(end)

        # Remove 0 and text length (always present)
        text_length = max(c.get("end_char", 0) for c in chunks)
        chunk_boundaries.discard(0)
        chunk_boundaries.discard(text_length)
        ground_truth = set(ground_truth)
        ground_truth.discard(0)
        ground_truth.discard(text_length)

        if not ground_truth:
            return 1.0

        # True positives: boundaries that match ground truth
        tp = len(chunk_boundaries & ground_truth)
        # False positives: chunk boundaries not in ground truth
        fp = len(chunk_boundaries - ground_truth)
        # False negatives: ground truth boundaries not in chunk boundaries
        fn = len(ground_truth - chunk_boundaries)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        if precision + recall == 0:
            return 0.0

        f1 = 2 * precision * recall / (precision + recall)
        return f1

    def _compute_semantic_coherence(self, chunks: list[dict[str, Any]]) -> float:
        """
        Compute semantic coherence within chunks.

        Measures average cosine similarity between adjacent chunks.
        Lower similarity between adjacent chunks = better boundaries.
        """
        if not self.embedder or len(chunks) < 2:
            return 0.0

        try:
            texts = [c.get("content", "") for c in chunks]
            embeddings = self.embedder.embed_batch(texts)

            similarities = []
            for i in range(len(embeddings) - 1):
                a = np.array(embeddings[i])
                b = np.array(embeddings[i + 1])
                sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
                similarities.append(sim)

            # Invert: lower similarity = better boundaries = higher coherence score
            avg_sim = np.mean(similarities)
            return float(1.0 - avg_sim)

        except Exception:
            return 0.0

    def compare_strategies(
        self,
        original_text: str,
        strategy_chunks: dict[str, list[dict[str, Any]]],
        ground_truth_boundaries: list[int] | None = None,
    ) -> dict[str, ChunkingMetrics]:
        """Compare multiple chunking strategies."""
        results = {}
        for strategy, chunks in strategy_chunks.items():
            results[strategy] = self.evaluate(
                original_text, chunks, ground_truth_boundaries
            )
        return results


def create_ground_truth_boundaries(text: str, method: str = "paragraph") -> list[int]:
    """Create ground truth boundaries for evaluation."""
    boundaries = [0]

    if method == "paragraph":
        # Paragraph boundaries
        import re
        for match in re.finditer(r"\n\s*\n", text):
            boundaries.append(match.start())
    elif method == "sentence":
        # Sentence boundaries
        import re
        for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])", text):
            boundaries.append(match.start())
    elif method == "section":
        # Markdown section boundaries
        import re
        for match in re.finditer(r"^#{1,6}\s+", text, re.MULTILINE):
            boundaries.append(match.start())

    boundaries.append(len(text))
    return sorted(set(boundaries))
