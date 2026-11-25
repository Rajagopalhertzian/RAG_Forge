"""
Embedding Evaluation Package

Provides metrics for evaluating embedding quality:
- Alignment (correlation with semantic similarity)
- Clustering Quality
- Retrieval Correlation
- Dimensionality Analysis
"""

from contextforge.evaluation.embedding.metrics import (
    AlignmentMetric,
    ClusteringMetric,
    DimensionalityMetric,
    EmbeddingEvaluator,
    EmbeddingPair,
    RetrievalCorrelationMetric,
    create_embedding_evaluator,
)

__all__ = [
    "EmbeddingPair",
    "AlignmentMetric",
    "ClusteringMetric",
    "RetrievalCorrelationMetric",
    "DimensionalityMetric",
    "EmbeddingEvaluator",
    "create_embedding_evaluator",
]
