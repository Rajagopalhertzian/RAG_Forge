"""
Embedding Evaluation Metrics

Evaluates quality of embedding models:
- Alignment: How well embeddings align with semantic similarity
- Clustering: Quality of embedding clusters
- Retrieval Correlation: Correlation between embedding similarity and retrieval relevance
- Dimensionality Analysis: Effective dimensionality, isotropy
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class EmbeddingPair:
    """A pair of texts with their embeddings and ground truth similarity."""

    text_a: str
    text_b: str
    embedding_a: np.ndarray
    embedding_b: np.ndarray
    ground_truth_similarity: float | None = None  # Human-annotated similarity (0-1)
    is_relevant: bool | None = None  # For retrieval evaluation


class AlignmentMetric:
    """
    Measures embedding alignment with semantic similarity.

    Uses Spearman/Pearson correlation between embedding cosine similarity
    and ground truth semantic similarity.
    """

    def evaluate(self, pairs: list[EmbeddingPair]) -> dict[str, float]:
        """
        Evaluate alignment.

        Args:
            pairs: List of embedding pairs with ground truth similarity

        Returns:
            Dict with correlation metrics
        """
        valid_pairs = [p for p in pairs if p.ground_truth_similarity is not None]
        if len(valid_pairs) < 3:
            return {"spearman": 0.0, "pearson": 0.0, "num_pairs": len(valid_pairs)}

        # Calculate cosine similarities
        cos_sims = []
        gt_sims = []

        for pair in valid_pairs:
            cos_sim = self._cosine_similarity(pair.embedding_a, pair.embedding_b)
            cos_sims.append(cos_sim)
            gt_sims.append(pair.ground_truth_similarity)

        # Spearman correlation (rank-based)
        spearman = self._spearman_correlation(cos_sims, gt_sims)
        # Pearson correlation (linear)
        pearson = self._pearson_correlation(cos_sims, gt_sims)

        return {
            "spearman": spearman,
            "pearson": pearson,
            "num_pairs": len(valid_pairs),
            "mean_cosine_sim": statistics.mean(cos_sims),
            "mean_gt_sim": statistics.mean(gt_sims),
        }

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _spearman_correlation(self, x: list[float], y: list[float]) -> float:
        """Calculate Spearman rank correlation."""
        # Rank the values
        x_ranked = self._rank(x)
        y_ranked = self._rank(y)
        return self._pearson_correlation(x_ranked, y_ranked)

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi * xi for xi in x)
        sum_y2 = sum(yi * yi for yi in y)

        numerator = n * sum_xy - sum_x * sum_y
        denominator = np.sqrt((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2))

        if denominator == 0:
            return 0.0

        return float(numerator / denominator)

    def _rank(self, values: list[float]) -> list[float]:
        """Assign ranks to values (average rank for ties)."""
        sorted_indices = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for rank, idx in enumerate(sorted_indices, 1):
            ranks[idx] = rank

        # Handle ties - average rank
        value_to_indices = {}
        for i, v in enumerate(values):
            value_to_indices.setdefault(v, []).append(i)

        for indices in value_to_indices.values():
            if len(indices) > 1:
                avg_rank = sum(ranks[i] for i in indices) / len(indices)
                for i in indices:
                    ranks[i] = avg_rank

        return ranks


class ClusteringMetric:
    """
    Evaluates clustering quality of embeddings.

    Uses silhouette score, Davies-Bouldin index, and cluster purity
    when ground truth labels are available.
    """

    def evaluate(
        self,
        embeddings: np.ndarray,
        labels: list[Any] = None,
        n_clusters: int = None,
    ) -> dict[str, float]:
        """
        Evaluate clustering quality.

        Args:
            embeddings: Array of shape (n_samples, n_dimensions)
            labels: Ground truth cluster labels (optional)
            n_clusters: Number of clusters for k-means (if no labels)

        Returns:
            Dict with clustering metrics
        """
        from sklearn.cluster import KMeans
        from sklearn.metrics import (
            adjusted_rand_index,
            davies_bouldin_score,
            normalized_mutual_info_score,
            silhouette_score,
        )

        results = {}

        if len(embeddings) < 2:
            return {"error": "Need at least 2 samples"}

        # Determine number of clusters
        if labels is not None:
            n_clusters = len(set(labels))
        elif n_clusters is None:
            n_clusters = min(10, len(embeddings) // 5)

        # Run k-means
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(embeddings)

        # Silhouette score (internal validation)
        try:
            results["silhouette"] = float(silhouette_score(embeddings, cluster_labels))
        except Exception:
            results["silhouette"] = 0.0

        # Davies-Bouldin index (lower is better)
        try:
            results["davies_bouldin"] = float(davies_bouldin_score(embeddings, cluster_labels))
        except Exception:
            results["davies_bouldin"] = float("inf")

        # Inertia (within-cluster sum of squares)
        results["inertia"] = float(kmeans.inertia_)

        # External validation if ground truth labels provided
        if labels is not None:
            results["adjusted_rand_index"] = float(adjusted_rand_index(labels, cluster_labels))
            results["normalized_mutual_info"] = float(normalized_mutual_info_score(labels, cluster_labels))

        # Cluster sizes
        unique, counts = np.unique(cluster_labels, return_counts=True)
        results["cluster_sizes"] = dict(zip(unique.tolist(), counts.tolist()))
        results["num_clusters"] = n_clusters

        return results


class RetrievalCorrelationMetric:
    """
    Measures correlation between embedding similarity and retrieval relevance.
    """

    def evaluate(self, pairs: list[EmbeddingPair]) -> dict[str, float]:
        """
        Evaluate retrieval correlation.

        Args:
            pairs: List of embedding pairs with is_relevant labels

        Returns:
            Dict with correlation metrics
        """
        valid_pairs = [p for p in pairs if p.is_relevant is not None]
        if len(valid_pairs) < 3:
            return {"auc": 0.5, "num_pairs": len(valid_pairs)}

        # Calculate cosine similarities
        similarities = []
        labels = []

        for pair in valid_pairs:
            cos_sim = self._cosine_similarity(pair.embedding_a, pair.embedding_b)
            similarities.append(cos_sim)
            labels.append(1.0 if pair.is_relevant else 0.0)

        # Calculate AUC-ROC
        auc = self._roc_auc(similarities, labels)

        # Calculate precision at various thresholds
        precisions = {}
        for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
            preds = [1.0 if s >= threshold else 0.0 for s in similarities]
            tp = sum(1 for p, l in zip(preds, labels) if p == 1 and l == 1)
            fp = sum(1 for p, l in zip(preds, labels) if p == 1 and l == 0)
            precisions[f"precision@{threshold}"] = tp / (tp + fp) if (tp + fp) > 0 else 0.0

        return {
            "auc": auc,
            "num_pairs": len(valid_pairs),
            "num_relevant": sum(labels),
            **precisions,
        }

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _roc_auc(self, scores: list[float], labels: list[float]) -> float:
        """Calculate ROC AUC using trapezoidal rule."""
        # Sort by score descending
        sorted_pairs = sorted(zip(scores, labels), key=lambda x: -x[0])

        tpr = 0.0
        fpr = 0.0
        prev_fpr = 0.0
        auc = 0.0

        total_pos = sum(labels)
        total_neg = len(labels) - total_pos

        if total_pos == 0 or total_neg == 0:
            return 0.5

        for score, label in sorted_pairs:
            if label == 1.0:
                tpr += 1.0 / total_pos
            else:
                fpr += 1.0 / total_neg
                auc += (fpr - prev_fpr) * tpr
                prev_fpr = fpr

        return auc


class DimensionalityMetric:
    """
    Analyzes embedding space dimensionality and isotropy.
    """

    def evaluate(self, embeddings: np.ndarray) -> dict[str, Any]:
        """
        Analyze embedding dimensionality.

        Args:
            embeddings: Array of shape (n_samples, n_dimensions)

        Returns:
            Dict with dimensionality metrics
        """
        n_samples, n_dims = embeddings.shape
        results = {"n_samples": n_samples, "n_dimensions": n_dims}

        # Center embeddings
        centered = embeddings - embeddings.mean(axis=0)

        # Covariance matrix
        cov = np.cov(centered, rowvar=False)

        # Eigenvalues
        eigenvals = np.linalg.eigvalsh(cov)
        eigenvals = np.sort(eigenvals)[::-1]  # Descending

        # Explained variance ratio
        total_var = eigenvals.sum()
        explained_var_ratio = eigenvals / total_var
        cumsum_var = np.cumsum(explained_var_ratio)

        # Effective dimensionality (participation ratio)
        # PR = (sum(lambda))^2 / sum(lambda^2)
        participation_ratio = float((eigenvals.sum()**2) / (eigenvals**2).sum())
        results["participation_ratio"] = participation_ratio
        results["participation_ratio_ratio"] = participation_ratio / n_dims

        # Number of dimensions for 90%, 95%, 99% variance
        for threshold in [0.90, 0.95, 0.99]:
            n_dims_needed = np.searchsorted(cumsum_var, threshold) + 1
            results[f"dims_{int(threshold*100)}pct_var"] = int(n_dims_needed)

        # Isotropy: how uniform are eigenvalues?
        # Perfect isotropy = all eigenvalues equal
        results["isotropy"] = float(eigenvals.min() / eigenvals.max()) if eigenvals.max() > 0 else 0.0

        # Condition number
        results["condition_number"] = float(eigenvals.max() / eigenvals.min()) if eigenvals.min() > 0 else float("inf")

        # Eigenvalue spectrum (top 10)
        results["top_eigenvalues"] = eigenvals[:10].tolist()
        results["explained_variance_top10"] = explained_var_ratio[:10].tolist()

        return results


class EmbeddingEvaluator:
    """
    Combined embedding evaluator.
    """

    def __init__(self):
        self.alignment = AlignmentMetric()
        self.clustering = ClusteringMetric()
        self.retrieval_correlation = RetrievalCorrelationMetric()
        self.dimensionality = DimensionalityMetric()

    def evaluate_alignment(self, pairs: list[EmbeddingPair]) -> dict[str, float]:
        return self.alignment.evaluate(pairs)

    def evaluate_clustering(
        self,
        embeddings: np.ndarray,
        labels: list[Any] = None,
        n_clusters: int = None,
    ) -> dict[str, float]:
        return self.clustering.evaluate(embeddings, labels, n_clusters)

    def evaluate_retrieval_correlation(self, pairs: list[EmbeddingPair]) -> dict[str, float]:
        return self.retrieval_correlation.evaluate(pairs)

    def evaluate_dimensionality(self, embeddings: np.ndarray) -> dict[str, Any]:
        return self.dimensionality.evaluate(embeddings)

    def evaluate_all(
        self,
        embeddings: np.ndarray,
        pairs: list[EmbeddingPair] = None,
        labels: list[Any] = None,
    ) -> dict[str, Any]:
        """
        Run all embedding evaluations.

        Args:
            embeddings: All embeddings array
            pairs: Pairs for alignment/retrieval correlation
            labels: Cluster labels for clustering evaluation

        Returns:
            Combined results
        """
        results = {
            "dimensionality": self.dimensionality.evaluate(embeddings),
            "clustering": self.clustering.evaluate(embeddings, labels),
        }

        if pairs:
            results["alignment"] = self.alignment.evaluate(pairs)
            results["retrieval_correlation"] = self.retrieval_correlation.evaluate(pairs)

        return results


def create_embedding_evaluator() -> EmbeddingEvaluator:
    """Create embedding evaluator."""
    return EmbeddingEvaluator()


def main():
    """CLI entry point for embedding evaluation."""
    import argparse
    import json
    from pathlib import Path

    import numpy as np

    parser = argparse.ArgumentParser(description="Run embedding evaluation on golden set")
    parser.add_argument("--golden-set", type=str, required=True, help="Path to golden set JSONL file")
    parser.add_argument("--output", type=str, required=True, help="Path to output results JSON file")
    parser.add_argument("--model", type=str, default="local", help="Embedding model to use (local, openai, bedrock)")
    args = parser.parse_args()

    golden_set_path = Path(args.golden_set)
    if not golden_set_path.exists():
        print(f"Golden set not found: {golden_set_path}")
        return 1

    # Load golden set
    pairs_data = []
    with open(golden_set_path) as f:
        for line in f:
            item = json.loads(line)
            pairs_data.append(item)

    # Create embedding pairs from golden set
    # For CI, we generate mock embeddings
    from src.contextforge.ingestion.embedders import create_embedder
    embedder = create_embedder(args.model)

    # Create pairs for evaluation
    embedding_pairs = []
    all_embeddings = []

    for i, item in enumerate(pairs_data[:50]):  # Limit for CI
        question = item.get("question", "")
        answer = item.get("answer", "")

        # Get embeddings
        emb_q = embedder.embed(question)
        emb_a = embedder.embed(answer)

        from src.contextforge.evaluation.embedding.metrics import EmbeddingPair
        pair = EmbeddingPair(
            text_a=question,
            text_b=answer,
            embedding_a=np.array(emb_q),
            embedding_b=np.array(emb_a),
            ground_truth_similarity=0.8 if i % 2 == 0 else 0.3,  # Mock ground truth
            is_relevant=i % 2 == 0,
        )
        embedding_pairs.append(pair)
        all_embeddings.append(np.array(emb_q))
        all_embeddings.append(np.array(emb_a))

    if all_embeddings:
        embeddings_array = np.vstack(all_embeddings)
    else:
        embeddings_array = np.array([])

    evaluator = create_embedding_evaluator()

    results = {}
    if embedding_pairs:
        results["alignment"] = evaluator.evaluate_alignment(embedding_pairs)
        results["retrieval_correlation"] = evaluator.evaluate_retrieval_correlation(embedding_pairs)

    if len(embeddings_array) > 0:
        results["dimensionality"] = evaluator.evaluate_dimensionality(embeddings_array)
        results["clustering"] = evaluator.evaluate_clustering(embeddings_array)

    with open(args.output, "w") as f:
        # Convert numpy types to native Python types
        def convert(obj):
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [convert(v) for v in obj]
            return obj

        json.dump(convert(results), f, indent=2)

    print(f"Embedding evaluation completed. Results saved to {args.output}")
    print(json.dumps(convert(results), indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
