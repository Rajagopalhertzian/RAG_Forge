#!/usr/bin/env python3
"""
ContextForge Embedding Drift Detection Script
Detects drift in embedding distributions over time using statistical methods.
"""

import os
import sys
import json
import argparse
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from scipy import stats
from scipy.spatial.distance import cosine, euclidean
from sklearn.metrics.pairwise import cosine_similarity
import boto3
import tempfile

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DriftResult:
    """Result of drift detection."""
    drift_detected: bool
    distance: float
    threshold: float
    method: str
    reference_stats: Dict[str, float]
    current_stats: Dict[str, float]
    details: Dict[str, Any]


class EmbeddingDriftDetector:
    """Detects drift in embedding distributions."""

    def __init__(
        self,
        threshold: float = 0.1,
        method: str = "cosine",
        sample_size: int = 10000
    ):
        self.threshold = threshold
        self.method = method
        self.sample_size = sample_size

    def load_embeddings(self, path: str) -> np.ndarray:
        """Load embeddings from file (supports .npy, .npz, .json, S3)."""
        if path.startswith('s3://'):
            return self._load_from_s3(path)
        elif path.endswith('.npy'):
            return np.load(path)
        elif path.endswith('.npz'):
            data = np.load(path)
            return data[list(data.keys())[0]]
        elif path.endswith('.json'):
            with open(path, 'r') as f:
                data = json.load(f)
            return np.array(data)
        else:
            raise ValueError(f"Unsupported file format: {path}")

    def _load_from_s3(self, s3_path: str) -> np.ndarray:
        """Load embeddings from S3."""
        # Parse s3://bucket/key
        parts = s3_path[5:].split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ''

        s3 = boto3.client('s3')

        with tempfile.NamedTemporaryFile(suffix='.npy', delete=False) as tmp:
            s3.download_file(bucket, key, tmp.name)
            return np.load(tmp.name)

    def compute_statistics(self, embeddings: np.ndarray) -> Dict[str, float]:
        """Compute statistical properties of embeddings."""
        # Sample if too large
        if len(embeddings) > self.sample_size:
            indices = np.random.choice(len(embeddings), self.sample_size, replace=False)
            embeddings = embeddings[indices]

        stats = {
            'mean': float(np.mean(embeddings)),
            'std': float(np.std(embeddings)),
            'min': float(np.min(embeddings)),
            'max': float(np.max(embeddings)),
            'median': float(np.median(embeddings)),
            'q25': float(np.percentile(embeddings, 25)),
            'q75': float(np.percentile(embeddings, 75)),
            'norm_mean': float(np.mean(np.linalg.norm(embeddings, axis=1))),
            'norm_std': float(np.std(np.linalg.norm(embeddings, axis=1))),
        }

        # Pairwise cosine similarities (sample)
        n_samples = min(1000, len(embeddings))
        if n_samples > 1:
            sample_idx = np.random.choice(len(embeddings), n_samples, replace=False)
            sample_embeddings = embeddings[sample_idx]
            similarities = cosine_similarity(sample_embeddings)
            # Get upper triangle (excluding diagonal)
            upper_tri = similarities[np.triu_indices_from(similarities, k=1)]
            stats['cosine_sim_mean'] = float(np.mean(upper_tri))
            stats['cosine_sim_std'] = float(np.std(upper_tri))
            stats['cosine_sim_min'] = float(np.min(upper_tri))
            stats['cosine_sim_max'] = float(np.max(upper_tri))

        return stats

    def detect_drift(
        self,
        reference_embeddings: np.ndarray,
        current_embeddings: np.ndarray
    ) -> DriftResult:
        """Detect drift between reference and current embeddings."""

        # Compute statistics
        ref_stats = self.compute_statistics(reference_embeddings)
        curr_stats = self.compute_statistics(current_embeddings)

        # Compute distance based on method
        if self.method == "cosine":
            distance = self._cosine_distance(reference_embeddings, current_embeddings)
        elif self.method == "euclidean":
            distance = self._euclidean_distance(reference_embeddings, current_embeddings)
        elif self.method == "kl_divergence":
            distance = self._kl_divergence(reference_embeddings, current_embeddings)
        elif self.method == "wasserstein":
            distance = self._wasserstein_distance(reference_embeddings, current_embeddings)
        elif self.method == "mmd":
            distance = self._mmd_distance(reference_embeddings, current_embeddings)
        elif self.method == "statistical":
            distance = self._statistical_distance(ref_stats, curr_stats)
        else:
            raise ValueError(f"Unknown method: {self.method}")

        drift_detected = distance > self.threshold

        return DriftResult(
            drift_detected=drift_detected,
            distance=float(distance),
            threshold=self.threshold,
            method=self.method,
            reference_stats=ref_stats,
            current_stats=curr_stats,
            details={
                'ref_shape': reference_embeddings.shape,
                'curr_shape': current_embeddings.shape,
                'ref_sample_size': min(self.sample_size, len(reference_embeddings)),
                'curr_sample_size': min(self.sample_size, len(current_embeddings))
            }
        )

    def _cosine_distance(self, ref: np.ndarray, curr: np.ndarray) -> float:
        """Compute cosine distance between mean embeddings."""
        ref_mean = np.mean(ref, axis=0)
        curr_mean = np.mean(curr, axis=0)
        return cosine(ref_mean, curr_mean)

    def _euclidean_distance(self, ref: np.ndarray, curr: np.ndarray) -> float:
        """Compute Euclidean distance between mean embeddings."""
        ref_mean = np.mean(ref, axis=0)
        curr_mean = np.mean(curr, axis=0)
        return euclidean(ref_mean, curr_mean) / np.sqrt(len(ref_mean))

    def _kl_divergence(self, ref: np.ndarray, curr: np.ndarray) -> float:
        """Compute KL divergence between embedding distributions (approximate)."""
        # Use histogram-based approximation
        bins = 50
        ref_flat = ref.flatten()
        curr_flat = curr.flatten()

        # Get common range
        min_val = min(ref_flat.min(), curr_flat.min())
        max_val = max(ref_flat.max(), curr_flat.max())

        ref_hist, _ = np.histogram(ref_flat, bins=bins, range=(min_val, max_val), density=True)
        curr_hist, _ = np.histogram(curr_flat, bins=bins, range=(min_val, max_val), density=True)

        # Add small epsilon to avoid log(0)
        eps = 1e-10
        ref_hist = ref_hist + eps
        curr_hist = curr_hist + eps

        # Normalize
        ref_hist = ref_hist / ref_hist.sum()
        curr_hist = curr_hist / curr_hist.sum()

        # KL divergence
        kl = np.sum(ref_hist * np.log(ref_hist / curr_hist))
        return float(kl)

    def _wasserstein_distance(self, ref: np.ndarray, curr: np.ndarray) -> float:
        """Compute Wasserstein distance (Earth Mover's Distance)."""
        from scipy.stats import wasserstein_distance
        # Use flattened embeddings (sample for efficiency)
        ref_flat = ref.flatten()
        curr_flat = curr.flatten()

        n_samples = min(10000, len(ref_flat), len(curr_flat))
        ref_sample = np.random.choice(ref_flat, n_samples, replace=False)
        curr_sample = np.random.choice(curr_flat, n_samples, replace=False)

        return float(wasserstein_distance(ref_sample, curr_sample))

    def _mmd_distance(self, ref: np.ndarray, curr: np.ndarray) -> float:
        """Compute Maximum Mean Discrepancy (MMD) with RBF kernel."""
        # Sample for efficiency
        n_samples = min(1000, len(ref), len(curr))
        ref_sample = ref[np.random.choice(len(ref), n_samples, replace=False)]
        curr_sample = curr[np.random.choice(len(curr), n_samples, replace=False)]

        # RBF kernel
        def rbf_kernel(X, Y, gamma=1.0):
            """Compute RBF kernel between X and Y."""
            XX = np.sum(X**2, axis=1, keepdims=True)
            YY = np.sum(Y**2, axis=1, keepdims=True)
            XY = X @ Y.T
            dist_sq = XX + YY.T - 2 * XY
            return np.exp(-gamma * dist_sq)

        K_xx = rbf_kernel(ref_sample, ref_sample)
        K_yy = rbf_kernel(curr_sample, curr_sample)
        K_xy = rbf_kernel(ref_sample, curr_sample)

        mmd = np.mean(K_xx) + np.mean(K_yy) - 2 * np.mean(K_xy)
        return float(np.sqrt(max(mmd, 0)))

    def _statistical_distance(self, ref_stats: Dict, curr_stats: Dict) -> float:
        """Compute distance based on statistical moments."""
        # Weighted combination of statistic differences
        weights = {
            'mean': 0.2,
            'std': 0.2,
            'norm_mean': 0.2,
            'norm_std': 0.1,
            'cosine_sim_mean': 0.3
        }

        distance = 0.0
        for key, weight in weights.items():
            if key in ref_stats and key in curr_stats:
                ref_val = ref_stats[key]
                curr_val = curr_stats[key]
                if ref_val != 0:
                    rel_diff = abs(ref_val - curr_val) / abs(ref_val)
                else:
                    rel_diff = abs(curr_val)
                distance += weight * rel_diff

        return distance

    def save_results(self, result: DriftResult, output_path: str):
        """Save drift detection results to JSON."""
        output_data = {
            'drift_detected': result.drift_detected,
            'distance': result.distance,
            'threshold': result.threshold,
            'method': result.method,
            'reference_stats': result.reference_stats,
            'current_stats': result.current_stats,
            'details': result.details
        }

        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)

        logger.info(f"Results saved to {output_path}")


async def main():
    parser = argparse.ArgumentParser(description="ContextForge Embedding Drift Detection")
    parser.add_argument("--reference-bucket", required=True, help="S3 bucket for reference embeddings")
    parser.add_argument("--reference-key", required=True, help="S3 key for reference embeddings")
    parser.add_argument("--current-bucket", required=True, help="S3 bucket for current embeddings")
    parser.add_argument("--current-key", required=True, help="S3 key for current embeddings")
    parser.add_argument("--threshold", type=float, default=0.1, help="Drift threshold")
    parser.add_argument("--method", choices=["cosine", "euclidean", "kl_divergence", "wasserstein", "mmd", "statistical"],
                        default="cosine", help="Drift detection method")
    parser.add_argument("--sample-size", type=int, default=10000, help="Sample size for statistics")
    parser.add_argument("--output", required=True, help="Output JSON file")

    args = parser.parse_args()

    detector = EmbeddingDriftDetector(
        threshold=args.threshold,
        method=args.method,
        sample_size=args.sample_size
    )

    # Load embeddings
    logger.info(f"Loading reference embeddings from s3://{args.reference_bucket}/{args.reference_key}")
    ref_embeddings = detector.load_embeddings(f"s3://{args.reference_bucket}/{args.reference_key}")
    logger.info(f"Reference embeddings shape: {ref_embeddings.shape}")

    logger.info(f"Loading current embeddings from s3://{args.current_bucket}/{args.current_key}")
    curr_embeddings = detector.load_embeddings(f"s3://{args.current_bucket}/{args.current_key}")
    logger.info(f"Current embeddings shape: {curr_embeddings.shape}")

    # Detect drift
    logger.info(f"Detecting drift using {args.method} method with threshold {args.threshold}")
    result = detector.detect_drift(ref_embeddings, curr_embeddings)

    # Print results
    print("\n" + "=" * 60)
    print("EMBEDDING DRIFT DETECTION RESULTS")
    print("=" * 60)
    print(f"Method:               {result.method}")
    print(f"Threshold:            {result.threshold}")
    print(f"Distance:             {result.distance:.6f}")
    print(f"Drift Detected:       {'YES ⚠️' if result.drift_detected else 'NO ✅'}")
    print(f"Reference Samples:    {result.details['ref_sample_size']:,}")
    print(f"Current Samples:      {result.details['curr_sample_size']:,}")
    print(f"Reference Shape:      {result.details['ref_shape']}")
    print(f"Current Shape:        {result.details['curr_shape']}")
    print("-" * 60)
    print("Reference Statistics:")
    for k, v in result.reference_stats.items():
        print(f"  {k}: {v:.6f}")
    print("-" * 60)
    print("Current Statistics:")
    for k, v in result.current_stats.items():
        print(f"  {k}: {v:.6f}")
    print("=" * 60)

    # Save results
    detector.save_results(result, args.output)

    sys.exit(1 if result.drift_detected else 0)


if __name__ == "__main__":
    asyncio.run(main())