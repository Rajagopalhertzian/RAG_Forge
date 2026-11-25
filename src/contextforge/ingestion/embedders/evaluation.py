"""
ContextForge Embedding Evaluation

Evaluation metrics for embedding quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


@dataclass
class EmbeddingMetrics:
    """Metrics for embedding evaluation."""

    # Alignment (query-document cosine similarity)
    alignment_score: float = 0.0

    # Clustering quality
    silhouette_score: float = 0.0
    n_clusters: int = 0

    # Retrieval proxy (MRR on golden set)
    mrr: float = 0.0
    recall_at_k: dict[int, float] = None

    # Basic stats
    dimensions: int = 0
    total_embeddings: int = 0

    def __post_init__(self):
        if self.recall_at_k is None:
            self.recall_at_k = {}


class EmbeddingEvaluator:
    """Evaluates embedding quality using multiple metrics."""

    def __init__(self, embedder=None):
        self.embedder = embedder

    def evaluate_alignment(
        self,
        queries: list[str],
        documents: list[str],
        relevance_labels: list[list[int]],  # For each query, list of relevant doc indices
    ) -> float:
        """
        Evaluate query-document alignment.

        Computes average cosine similarity between queries and their relevant documents.
        """
        if not self.embedder or not queries or not documents:
            return 0.0

        query_embeddings = self.embedder.embed_batch(queries)
        doc_embeddings = self.embedder.embed_batch(documents)

        query_embeddings = np.array(query_embeddings)
        doc_embeddings = np.array(doc_embeddings)

        # Normalize
        query_norms = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
        doc_norms = np.linalg.norm(doc_embeddings, axis=1, keepdims=True)

        query_embeddings = query_embeddings / (query_norms + 1e-8)
        doc_embeddings = doc_embeddings / (doc_norms + 1e-8)

        # Compute similarities
        similarities = query_embeddings @ doc_embeddings.T

        # Average similarity for relevant pairs
        total_sim = 0.0
        count = 0

        for q_idx, relevant_docs in enumerate(relevance_labels):
            for d_idx in relevant_docs:
                if 0 <= d_idx < len(documents):
                    total_sim += similarities[q_idx, d_idx]
                    count += 1

        return float(total_sim / count) if count > 0 else 0.0

    def evaluate_clustering(
        self,
        texts: list[str],
        labels: list[int] | None = None,
        n_clusters: int | None = None,
    ) -> float:
        """
        Evaluate clustering quality using silhouette score.

        If labels provided, uses them. Otherwise clusters with KMeans.
        """
        if not self.embedder or not texts:
            return 0.0

        embeddings = np.array(self.embedder.embed_batch(texts))

        if labels is not None:
            # Use provided labels
            unique_labels = len(set(labels))
            if unique_labels < 2:
                return 0.0
            return float(silhouette_score(embeddings, labels))
        else:
            # Cluster with KMeans
            if n_clusters is None:
                n_clusters = min(10, len(texts) // 5)
            if n_clusters < 2:
                return 0.0

            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(embeddings)

            return float(silhouette_score(embeddings, cluster_labels))

    def evaluate_retrieval(
        self,
        queries: list[str],
        documents: list[str],
        ground_truth: dict[int, list[int]],  # query_idx -> list of relevant doc_indices
        k_values: list[int] = [1, 5, 10, 20],
    ) -> dict[str, Any]:
        """
        Evaluate retrieval quality using MRR and Recall@K.

        This is a proxy metric using the embedder directly for retrieval.
        """
        if not self.embedder or not queries or not documents:
            return {"mrr": 0.0, "recall_at_k": {}}

        query_embeddings = np.array(self.embedder.embed_batch(queries))
        doc_embeddings = np.array(self.embedder.embed_batch(documents))

        # Normalize
        query_embeddings = query_embeddings / (np.linalg.norm(query_embeddings, axis=1, keepdims=True) + 1e-8)
        doc_embeddings = doc_embeddings / (np.linalg.norm(doc_embeddings, axis=1, keepdims=True) + 1e-8)

        # Compute similarities
        similarities = query_embeddings @ doc_embeddings.T

        # Get top-k for each query
        mrr_sum = 0.0
        recall_at_k = dict.fromkeys(k_values, 0.0)

        for q_idx, relevant_docs in ground_truth.items():
            if q_idx >= len(queries):
                continue

            # Get ranked document indices
            ranked = np.argsort(similarities[q_idx])[::-1]

            # MRR
            for rank, doc_idx in enumerate(ranked):
                if doc_idx in relevant_docs:
                    mrr_sum += 1.0 / (rank + 1)
                    break

            # Recall@K
            for k in k_values:
                top_k = set(ranked[:k])
                relevant_set = set(relevant_docs)
                if relevant_set:
                    recall_at_k[k] += len(top_k & relevant_set) / len(relevant_set)

        n_queries = len(ground_truth)
        return {
            "mrr": mrr_sum / n_queries if n_queries > 0 else 0.0,
            "recall_at_k": {k: v / n_queries for k, v in recall_at_k.items()},
        }

    def evaluate(
        self,
        texts: list[str],
        queries: list[str] | None = None,
        documents: list[str] | None = None,
        relevance_labels: list[list[int]] | None = None,
        ground_truth: dict[int, list[int]] | None = None,
        labels: list[int] | None = None,
    ) -> EmbeddingMetrics:
        """Run all available evaluations."""
        metrics = EmbeddingMetrics()

        if not self.embedder:
            return metrics

        # Get embeddings for stats
        embeddings = self.embedder.embed_batch(texts)
        metrics.dimensions = len(embeddings[0]) if embeddings else 0
        metrics.total_embeddings = len(embeddings)

        # Alignment
        if queries and documents and relevance_labels:
            metrics.alignment_score = self.evaluate_alignment(queries, documents, relevance_labels)

        # Clustering
        if len(texts) > 1:
            metrics.silhouette_score = self.evaluate_clustering(texts, labels)
            metrics.n_clusters = len(set(labels)) if labels else min(10, len(texts) // 5)

        # Retrieval proxy
        if queries and documents and ground_truth:
            retrieval_metrics = self.evaluate_retrieval(queries, documents, ground_truth)
            metrics.mrr = retrieval_metrics["mrr"]
            metrics.recall_at_k = retrieval_metrics["recall_at_k"]

        return metrics


def create_golden_set(
    texts: list[str],
    n_queries: int = 10,
    n_relevant_per_query: int = 3,
) -> tuple[list[str], dict[int, list[int]]]:
    """
    Create a simple golden set for evaluation.

    Returns (queries, ground_truth) where ground_truth maps query_idx to relevant doc indices.
    """

    if len(texts) < n_queries * n_relevant_per_query:
        raise ValueError("Not enough texts for golden set")

    # Simple approach: use first n_queries texts as queries
    # and next n_relevant_per_query as relevant for each
    queries = texts[:n_queries]
    ground_truth = {}

    for i in range(n_queries):
        start = n_queries + i * n_relevant_per_query
        end = start + n_relevant_per_query
        ground_truth[i] = list(range(start, min(end, len(texts))))

    return queries, ground_truth
