"""
Chunking Evaluation Package

Provides metrics for evaluating chunking quality:
- Boundary Preservation
- Semantic Coherence
- Chunk Size Distribution
- Overlap Quality
"""

from contextforge.evaluation.chunking.metrics import (
    BoundaryPreservationMetric,
    Chunk,
    ChunkingEvaluator,
    ChunkingResult,
    ChunkSizeMetric,
    OverlapQualityMetric,
    SemanticCoherenceMetric,
    create_chunking_evaluator,
)

__all__ = [
    "Chunk",
    "ChunkingResult",
    "BoundaryPreservationMetric",
    "SemanticCoherenceMetric",
    "ChunkSizeMetric",
    "OverlapQualityMetric",
    "ChunkingEvaluator",
    "create_chunking_evaluator",
]
