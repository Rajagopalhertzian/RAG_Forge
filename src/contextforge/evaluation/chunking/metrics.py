"""
Chunking Evaluation Metrics

Evaluates quality of text chunking strategies:
- Boundary Preservation: Does chunking respect semantic boundaries?
- Semantic Coherence: Are chunks semantically coherent?
- Chunk Size Distribution: Statistics on chunk sizes
- Overlap Quality: Quality of overlapping regions
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """Represents a text chunk."""

    id: str
    content: str
    start_char: int
    end_char: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.content)

    @property
    def token_count(self) -> int:
        # Rough estimate: 1 token ≈ 4 chars
        return len(self.content) // 4


@dataclass
class ChunkingResult:
    """Result of chunking a document."""

    chunks: list[Chunk]
    original_text: str
    strategy: str
    config: dict[str, Any] = field(default_factory=dict)


class BoundaryPreservationMetric:
    """
    Measures how well chunking preserves semantic boundaries (paragraphs, sections, sentences).
    """

    def __init__(self):
        self.boundary_types = ["paragraph", "section", "sentence"]

    def evaluate(self, result: ChunkingResult) -> dict[str, float]:
        """
        Evaluate boundary preservation.

        Returns:
            Dict with scores for each boundary type (0-1, higher is better)
        """
        scores = {}
        text = result.original_text
        chunks = result.chunks

        # Paragraph boundaries
        scores["paragraph"] = self._check_boundaries(
            text, chunks, self._find_paragraph_boundaries(text)
        )

        # Section boundaries (headers)
        scores["section"] = self._check_boundaries(
            text, chunks, self._find_section_boundaries(text)
        )

        # Sentence boundaries
        scores["sentence"] = self._check_boundaries(
            text, chunks, self._find_sentence_boundaries(text)
        )

        # Overall score (weighted average)
        scores["overall"] = (
            scores["paragraph"] * 0.4 +
            scores["section"] * 0.3 +
            scores["sentence"] * 0.3
        )

        return scores

    def _find_paragraph_boundaries(self, text: str) -> list[int]:
        """Find paragraph boundary positions (double newlines)."""
        boundaries = [0]
        pos = 0
        while True:
            idx = text.find("\n\n", pos)
            if idx == -1:
                break
            boundaries.append(idx + 2)  # After the newlines
            pos = idx + 2
        boundaries.append(len(text))
        return boundaries

    def _find_section_boundaries(self, text: str) -> list[int]:
        """Find section boundaries (markdown headers)."""
        import re
        boundaries = [0]
        for match in re.finditer(r'^#{1,6}\s+', text, re.MULTILINE):
            boundaries.append(match.start())
        boundaries.append(len(text))
        return sorted(set(boundaries))

    def _find_sentence_boundaries(self, text: str) -> list[int]:
        """Find sentence boundaries."""
        import re
        boundaries = [0]
        for match in re.finditer(r'(?<=[.!?])\s+(?=[A-Z])', text):
            boundaries.append(match.end())
        boundaries.append(len(text))
        return boundaries

    def _check_boundaries(
        self,
        text: str,
        chunks: list[Chunk],
        boundaries: list[int],
    ) -> float:
        """Check how many boundaries align with chunk boundaries."""
        if len(boundaries) <= 2:  # Only start/end
            return 1.0

        chunk_boundaries = set()
        for chunk in chunks:
            chunk_boundaries.add(chunk.start_char)
            chunk_boundaries.add(chunk.end_char)

        aligned = 0
        for boundary in boundaries[1:-1]:  # Exclude start/end
            # Check if boundary aligns with chunk boundary (within 10 chars)
            for cb in chunk_boundaries:
                if abs(boundary - cb) <= 10:
                    aligned += 1
                    break

        return aligned / (len(boundaries) - 2)


class SemanticCoherenceMetric:
    """
    Measures semantic coherence within chunks using embedding similarity.
    """

    def __init__(self, embedding_fn=None):
        """
        Args:
            embedding_fn: Function(text) -> embedding vector
                         If None, uses heuristic based on word overlap
        """
        self.embedding_fn = embedding_fn

    def evaluate(self, result: ChunkingResult) -> dict[str, float]:
        """
        Evaluate semantic coherence of chunks.

        Returns:
            Dict with coherence scores
        """
        if len(result.chunks) < 2:
            return {"coherence": 1.0, "avg_pairwise_similarity": 1.0}

        chunks = result.chunks

        if self.embedding_fn:
            return self._evaluate_with_embeddings(chunks)
        else:
            return self._evaluate_heuristic(chunks)

    def _evaluate_with_embeddings(self, chunks: list[Chunk]) -> dict[str, float]:
        """Evaluate using embeddings (requires embedding function)."""
        embeddings = [self.embedding_fn(c.content) for c in chunks]

        # Calculate pairwise similarities
        import numpy as np
        similarities = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sim = np.dot(embeddings[i], embeddings[j]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
                )
                similarities.append(sim)

        return {
            "coherence": float(np.mean(similarities)) if similarities else 1.0,
            "avg_pairwise_similarity": float(np.mean(similarities)) if similarities else 1.0,
            "min_similarity": float(np.min(similarities)) if similarities else 1.0,
        }

    def _evaluate_heuristic(self, chunks: list[Chunk]) -> dict[str, float]:
        """Heuristic evaluation using word overlap."""
        similarities = []

        for i in range(len(chunks)):
            for j in range(i + 1, len(chunks)):
                words_i = set(chunks[i].content.lower().split())
                words_j = set(chunks[j].content.lower().split())

                # Remove stop words
                stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
                words_i -= stop_words
                words_j -= stop_words

                if words_i and words_j:
                    overlap = len(words_i & words_j)
                    union = len(words_i | words_j)
                    similarities.append(overlap / union if union > 0 else 0.0)

        return {
            "coherence": statistics.mean(similarities) if similarities else 1.0,
            "avg_pairwise_similarity": statistics.mean(similarities) if similarities else 1.0,
            "min_similarity": min(similarities) if similarities else 1.0,
        }


class ChunkSizeMetric:
    """
    Analyzes chunk size distribution.
    """

    def evaluate(self, result: ChunkingResult) -> dict[str, Any]:
        """
        Evaluate chunk size statistics.

        Returns:
            Dict with size statistics
        """
        chunks = result.chunks
        if not chunks:
            return {"error": "No chunks"}

        lengths = [c.length for c in chunks]
        token_counts = [c.token_count for c in chunks]

        return {
            "num_chunks": len(chunks),
            "char_length": {
                "mean": statistics.mean(lengths),
                "median": statistics.median(lengths),
                "stdev": statistics.stdev(lengths) if len(lengths) > 1 else 0,
                "min": min(lengths),
                "max": max(lengths),
            },
            "token_count": {
                "mean": statistics.mean(token_counts),
                "median": statistics.median(token_counts),
                "stdev": statistics.stdev(token_counts) if len(token_counts) > 1 else 0,
                "min": min(token_counts),
                "max": max(token_counts),
            },
        }


class OverlapQualityMetric:
    """
    Evaluates quality of chunk overlaps.
    """

    def evaluate(self, result: ChunkingResult) -> dict[str, float]:
        """
        Evaluate overlap quality between adjacent chunks.

        Returns:
            Dict with overlap metrics
        """
        chunks = result.chunks
        if len(chunks) < 2:
            return {"overlap_ratio": 0.0, "overlap_consistency": 1.0}

        overlap_ratios = []
        overlap_consistency = []

        for i in range(len(chunks) - 1):
            chunk_a = chunks[i]
            chunk_b = chunks[i + 1]

            # Calculate character overlap
            overlap_start = max(chunk_a.start_char, chunk_b.start_char)
            overlap_end = min(chunk_a.end_char, chunk_b.end_char)

            if overlap_start < overlap_end:
                overlap_chars = overlap_end - overlap_start
                chunk_a_len = chunk_a.length
                chunk_b_len = chunk_b.length
                avg_len = (chunk_a_len + chunk_b_len) / 2
                overlap_ratios.append(overlap_chars / avg_len if avg_len > 0 else 0)
            else:
                overlap_ratios.append(0.0)

        # Consistency: how uniform are the overlaps
        if overlap_ratios:
            mean_overlap = statistics.mean(overlap_ratios)
            stdev_overlap = statistics.stdev(overlap_ratios) if len(overlap_ratios) > 1 else 0
            consistency = 1.0 - min(1.0, stdev_overlap / (mean_overlap + 1e-6))
        else:
            mean_overlap = 0.0
            consistency = 1.0

        return {
            "avg_overlap_ratio": mean_overlap,
            "overlap_consistency": consistency,
            "overlap_ratios": overlap_ratios,
        }


class ChunkingEvaluator:
    """
    Combined chunking evaluator.
    """

    def __init__(self, embedding_fn=None):
        self.boundary_metric = BoundaryPreservationMetric()
        self.coherence_metric = SemanticCoherenceMetric(embedding_fn)
        self.size_metric = ChunkSizeMetric()
        self.overlap_metric = OverlapQualityMetric()

    def evaluate(self, result: ChunkingResult) -> dict[str, Any]:
        """
        Run all chunking evaluations.

        Returns:
            Combined evaluation results
        """
        return {
            "boundary_preservation": self.boundary_metric.evaluate(result),
            "semantic_coherence": self.coherence_metric.evaluate(result),
            "chunk_sizes": self.size_metric.evaluate(result),
            "overlap_quality": self.overlap_metric.evaluate(result),
        }

    def evaluate_batch(self, results: list[ChunkingResult]) -> list[dict[str, Any]]:
        """Evaluate multiple chunking results."""
        return [self.evaluate(r) for r in results]


def create_chunking_evaluator(embedding_fn=None) -> ChunkingEvaluator:
    """Create chunking evaluator."""
    return ChunkingEvaluator(embedding_fn)


def main():
    """CLI entry point for chunking evaluation."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Run chunking evaluation on golden set")
    parser.add_argument("--golden-set", type=str, required=True, help="Path to golden set JSONL file")
    parser.add_argument("--output", type=str, required=True, help="Path to output results JSON file")
    parser.add_argument("--strategy", type=str, default="semantic", help="Chunking strategy to evaluate")
    args = parser.parse_args()

    golden_set_path = Path(args.golden_set)
    if not golden_set_path.exists():
        print(f"Golden set not found: {golden_set_path}")
        return 1

    # Load golden set to get documents
    documents = []
    with open(golden_set_path) as f:
        for line in f:
            item = json.loads(line)
            # Use relevant_docs as document references
            for doc_id in item.get("relevant_docs", []):
                if doc_id not in documents:
                    documents.append(doc_id)

    # Create mock chunks for evaluation (in real use, this would chunk actual documents)
    # For CI, we simulate chunking results
    from src.contextforge.ingestion.chunkers import create_chunker
    chunker = create_chunker(args.strategy)

    results = []
    for doc_id in documents[:10]:  # Limit for CI
        # Create a sample document content
        content = f"Sample document {doc_id} " * 50
        chunks = chunker.chunk(content)

        chunking_result = ChunkingResult(
            chunks=[Chunk(id=f"{doc_id}_{i}", content=c, start_char=0, end_char=len(c)) for i, c in enumerate(chunks)],
            original_text=content,
            strategy=args.strategy,
        )
        results.append(chunking_result)

    evaluator = create_chunking_evaluator()
    eval_results = evaluator.evaluate_batch(results)

    # Aggregate results
    aggregated = {
        "strategy": args.strategy,
        "num_documents": len(results),
        "boundary_preservation": {
            "paragraph": sum(r["boundary_preservation"]["paragraph"] for r in eval_results) / len(eval_results),
            "section": sum(r["boundary_preservation"]["section"] for r in eval_results) / len(eval_results),
            "sentence": sum(r["boundary_preservation"]["sentence"] for r in eval_results) / len(eval_results),
            "overall": sum(r["boundary_preservation"]["overall"] for r in eval_results) / len(eval_results),
        },
        "semantic_coherence": {
            "coherence": sum(r["semantic_coherence"]["coherence"] for r in eval_results) / len(eval_results),
        },
        "chunk_sizes": {
            "mean_char_length": sum(r["chunk_sizes"]["char_length"]["mean"] for r in eval_results) / len(eval_results),
            "mean_token_count": sum(r["chunk_sizes"]["token_count"]["mean"] for r in eval_results) / len(eval_results),
        },
        "overlap_quality": {
            "avg_overlap_ratio": sum(r["overlap_quality"]["avg_overlap_ratio"] for r in eval_results) / len(eval_results),
        },
    }

    with open(args.output, "w") as f:
        json.dump(aggregated, f, indent=2)

    print(f"Chunking evaluation completed. Results saved to {args.output}")
    print(json.dumps(aggregated, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
