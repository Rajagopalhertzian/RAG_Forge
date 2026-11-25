"""
Retrieval Evaluation Metrics

Implements standard IR metrics for evaluating retrieval quality:
- MRR@k (Mean Reciprocal Rank)
- nDCG@k (Normalized Discounted Cumulative Gain)
- Recall@k
- Precision@k
- Latency metrics (p50, p95, p99)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalMetrics:
    """Container for retrieval evaluation metrics."""

    mrr_at_k: dict[int, float] = field(default_factory=dict)
    ndcg_at_k: dict[int, float] = field(default_factory=dict)
    recall_at_k: dict[int, float] = field(default_factory=dict)
    precision_at_k: dict[int, float] = field(default_factory=dict)
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    total_queries: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "mrr_at_k": self.mrr_at_k,
            "ndcg_at_k": self.ndcg_at_k,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "total_queries": self.total_queries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalMetrics:
        """Create from dictionary."""
        return cls(
            mrr_at_k=data.get("mrr_at_k", {}),
            ndcg_at_k=data.get("ndcg_at_k", {}),
            recall_at_k=data.get("recall_at_k", {}),
            precision_at_k=data.get("precision_at_k", {}),
            latency_p50=data.get("latency_p50", 0.0),
            latency_p95=data.get("latency_p95", 0.0),
            latency_p99=data.get("latency_p99", 0.0),
            total_queries=data.get("total_queries", 0),
        )


def reciprocal_rank(relevant_docs: set[str], retrieved_docs: list[str], k: int) -> float:
    """
    Calculate Reciprocal Rank at k.

    Args:
        relevant_docs: Set of relevant document IDs
        retrieved_docs: List of retrieved document IDs (ranked)
        k: Cutoff rank

    Returns:
        Reciprocal rank (1/rank of first relevant doc) or 0 if none found
    """
    for i, doc_id in enumerate(retrieved_docs[:k], 1):
        if doc_id in relevant_docs:
            return 1.0 / i
    return 0.0


def dcg_at_k(relevant_docs: set[str], retrieved_docs: list[str], k: int) -> float:
    """
    Calculate Discounted Cumulative Gain at k.

    Args:
        relevant_docs: Set of relevant document IDs
        retrieved_docs: List of retrieved document IDs (ranked)
        k: Cutoff rank

    Returns:
        DCG score
    """
    dcg = 0.0
    for i, doc_id in enumerate(retrieved_docs[:k], 1):
        if doc_id in relevant_docs:
            # Binary relevance: 1 for relevant, 0 for non-relevant
            relevance = 1.0
            dcg += relevance / math.log2(i + 1)
    return dcg


def ndcg_at_k(relevant_docs: set[str], retrieved_docs: list[str], k: int) -> float:
    """
    Calculate Normalized Discounted Cumulative Gain at k.

    Args:
        relevant_docs: Set of relevant document IDs
        retrieved_docs: List of retrieved document IDs (ranked)
        k: Cutoff rank

    Returns:
        NDCG score (0 to 1)
    """
    if not relevant_docs:
        return 1.0  # Perfect score if no relevant docs expected

    dcg = dcg_at_k(relevant_docs, retrieved_docs, k)

    # Ideal DCG: all relevant docs at top
    ideal_retrieved = list(relevant_docs)[:k]
    idcg = dcg_at_k(relevant_docs, ideal_retrieved, k)

    if idcg == 0:
        return 1.0

    return dcg / idcg


def recall_at_k(relevant_docs: set[str], retrieved_docs: list[str], k: int) -> float:
    """
    Calculate Recall at k.

    Args:
        relevant_docs: Set of relevant document IDs
        retrieved_docs: List of retrieved document IDs (ranked)
        k: Cutoff rank

    Returns:
        Recall score (0 to 1)
    """
    if not relevant_docs:
        return 1.0

    retrieved_set = set(retrieved_docs[:k])
    intersection = relevant_docs & retrieved_set
    return len(intersection) / len(relevant_docs)


def precision_at_k(relevant_docs: set[str], retrieved_docs: list[str], k: int) -> float:
    """
    Calculate Precision at k.

    Args:
        relevant_docs: Set of relevant document IDs
        retrieved_docs: List of retrieved document IDs (ranked)
        k: Cutoff rank

    Returns:
        Precision score (0 to 1)
    """
    if k == 0:
        return 0.0

    retrieved_set = set(retrieved_docs[:k])
    intersection = relevant_docs & retrieved_set
    return len(intersection) / k


def calculate_latency_percentiles(latencies: list[float]) -> tuple[float, float, float]:
    """
    Calculate p50, p95, p99 latency percentiles.

    Args:
        latencies: List of latency values in milliseconds

    Returns:
        Tuple of (p50, p95, p99)
    """
    if not latencies:
        return 0.0, 0.0, 0.0

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    def percentile(p: float) -> float:
        idx = (p / 100) * (n - 1)
        if idx.is_integer():
            return sorted_latencies[int(idx)]
        lower = sorted_latencies[int(idx)]
        upper = sorted_latencies[int(idx) + 1]
        return lower + (upper - lower) * (idx - int(idx))

    return percentile(50), percentile(95), percentile(99)


def evaluate_retrieval(
    queries: list[dict[str, Any]],
    k_values: list[int] = None,
) -> RetrievalMetrics:
    """
    Evaluate retrieval performance across multiple queries.

    Args:
        queries: List of query dicts with keys:
            - query_id: Unique identifier
            - query_text: Query text
            - relevant_docs: Set of relevant document IDs
            - retrieved_docs: List of retrieved document IDs (ranked)
            - latency_ms: Retrieval latency in milliseconds
        k_values: List of k values to evaluate (default: [1, 3, 5, 10, 20])

    Returns:
        RetrievalMetrics with aggregated scores
    """
    if k_values is None:
        k_values = [1, 3, 5, 10, 20]

    mrr_scores: dict[int, list[float]] = {k: [] for k in k_values}
    ndcg_scores: dict[int, list[float]] = {k: [] for k in k_values}
    recall_scores: dict[int, list[float]] = {k: [] for k in k_values}
    precision_scores: dict[int, list[float]] = {k: [] for k in k_values}
    latencies: list[float] = []

    for query in queries:
        relevant = set(query.get("relevant_docs", []))
        retrieved = query.get("retrieved_docs", [])
        latency = query.get("latency_ms", 0.0)

        latencies.append(latency)

        for k in k_values:
            mrr_scores[k].append(reciprocal_rank(relevant, retrieved, k))
            ndcg_scores[k].append(ndcg_at_k(relevant, retrieved, k))
            recall_scores[k].append(recall_at_k(relevant, retrieved, k))
            precision_scores[k].append(precision_at_k(relevant, retrieved, k))

    # Aggregate scores (mean)
    metrics = RetrievalMetrics(total_queries=len(queries))

    for k in k_values:
        metrics.mrr_at_k[k] = statistics.mean(mrr_scores[k]) if mrr_scores[k] else 0.0
        metrics.ndcg_at_k[k] = statistics.mean(ndcg_scores[k]) if ndcg_scores[k] else 0.0
        metrics.recall_at_k[k] = statistics.mean(recall_scores[k]) if recall_scores[k] else 0.0
        metrics.precision_at_k[k] = statistics.mean(precision_scores[k]) if precision_scores[k] else 0.0

    metrics.latency_p50, metrics.latency_p95, metrics.latency_p99 = calculate_latency_percentiles(latencies)

    return metrics


def check_thresholds(
    metrics: RetrievalMetrics,
    mrr_threshold: float = 0.65,
    latency_p95_threshold: float = 800.0,
    k: int = 10,
) -> tuple[bool, list[str]]:
    """
    Check if metrics meet minimum thresholds.

    Args:
        metrics: RetrievalMetrics to check
        mrr_threshold: Minimum MRR@k (default: 0.65 at k=10)
        latency_p95_threshold: Maximum p95 latency in ms (default: 800ms)
        k: k value for MRR threshold check

    Returns:
        Tuple of (passed, list of failure messages)
    """
    failures = []

    mrr_at_k = metrics.mrr_at_k.get(k, 0.0)
    if mrr_at_k < mrr_threshold:
        failures.append(f"MRR@{k} = {mrr_at_k:.4f} < {mrr_threshold}")

    if metrics.latency_p95 > latency_p95_threshold:
        failures.append(f"Latency p95 = {metrics.latency_p95:.2f}ms > {latency_p95_threshold}ms")

    return len(failures) == 0, failures
