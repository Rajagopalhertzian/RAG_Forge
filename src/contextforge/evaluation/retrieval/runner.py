"""
CI-Integrated Retrieval Evaluation Runner

Runs retrieval evaluation against golden QA sets with threshold gating.
Designed for CI/CD integration - exits with non-zero code on threshold failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contextforge.evaluation.retrieval.dataset import GoldenDataset, load_golden_set
from contextforge.evaluation.retrieval.metrics import (
    RetrievalMetrics,
    check_thresholds,
    evaluate_retrieval,
)


@dataclass
class EvaluationConfig:
    """Configuration for retrieval evaluation."""

    golden_set_version: str = "v1"
    golden_set_path: Path = None
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])
    mrr_threshold: float = 0.65
    mrr_threshold_k: int = 10
    latency_p95_threshold: float = 800.0  # ms
    output_path: Path = None
    verbose: bool = False


@dataclass
class EvaluationResult:
    """Result of evaluation run."""

    config: EvaluationConfig
    metrics: RetrievalMetrics
    passed: bool
    failures: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "config": {
                "golden_set_version": self.config.golden_set_version,
                "k_values": self.config.k_values,
                "mrr_threshold": self.config.mrr_threshold,
                "mrr_threshold_k": self.config.mrr_threshold_k,
                "latency_p95_threshold": self.config.latency_p95_threshold,
            },
            "metrics": self.metrics.to_dict(),
            "passed": self.passed,
            "failures": self.failures,
            "duration_seconds": self.duration_seconds,
        }


class RetrievalEvaluator:
    """
    Runs retrieval evaluation against a golden QA dataset.

    In production, this would call the actual retrieval pipeline.
    For CI, we simulate with a mock or connect to a running service.
    """

    def __init__(
        self,
        config: EvaluationConfig,
        retrieval_fn: Callable[[str], tuple[list[str], float]] = None,
    ):
        """
        Initialize evaluator.

        Args:
            config: Evaluation configuration
            retrieval_fn: Function(query) -> (retrieved_doc_ids, latency_ms)
                         If None, uses mock retrieval for testing
        """
        self.config = config
        self.retrieval_fn = retrieval_fn or self._mock_retrieval

    async def _mock_retrieval(self, query: str) -> tuple[list[str], float]:
        """Mock retrieval for testing - returns empty results with simulated latency."""
        await asyncio.sleep(0.01)  # Simulate 10ms latency
        return [], 10.0

    async def run(self) -> EvaluationResult:
        """Run the full evaluation."""
        start_time = time.time()

        # Load golden dataset
        if self.config.golden_set_path:
            dataset = GoldenDataset.from_jsonl(self.config.golden_set_path)
        else:
            dataset = load_golden_set(self.config.golden_set_version)

        if self.config.verbose:
            print(f"Loaded golden set: {len(dataset)} QA pairs (version: {dataset.version})")
            stats = dataset.stats()
            print(f"  Categories: {stats['categories']}")
            print(f"  Difficulties: {stats['difficulties']}")

        # Validate dataset
        valid, errors = dataset.validate_all()
        if not valid:
            raise ValueError(f"Golden set validation failed: {errors}")

        # Run retrieval for each query
        queries = []
        for qa in dataset:
            retrieved_docs, latency_ms = await self.retrieval_fn(qa.question)
            queries.append({
                "query_id": qa.id,
                "query_text": qa.question,
                "relevant_docs": qa.relevant_docs,
                "retrieved_docs": retrieved_docs,
                "latency_ms": latency_ms,
            })

            if self.config.verbose:
                print(f"Query {qa.id}: {len(retrieved_docs)} retrieved, {latency_ms:.2f}ms")

        # Evaluate
        metrics = evaluate_retrieval(queries, self.config.k_values)

        # Check thresholds
        passed, failures = check_thresholds(
            metrics,
            mrr_threshold=self.config.mrr_threshold,
            latency_p95_threshold=self.config.latency_p95_threshold,
            k=self.config.mrr_threshold_k,
        )

        duration = time.time() - start_time

        result = EvaluationResult(
            config=self.config,
            metrics=metrics,
            passed=passed,
            failures=failures,
            duration_seconds=duration,
        )

        # Output results
        if self.config.output_path:
            self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.output_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)

        return result


async def run_evaluation(
    golden_set_version: str = "v1",
    golden_set_path: str = None,
    mrr_threshold: float = 0.65,
    latency_p95_threshold: float = 800.0,
    output_path: str = None,
    verbose: bool = False,
    retrieval_fn: Callable[[str], tuple[list[str], float]] = None,
) -> EvaluationResult:
    """
    Convenience function to run evaluation.

    Args:
        golden_set_version: Version of golden set to use
        golden_set_path: Explicit path to golden set JSONL
        mrr_threshold: Minimum MRR@10 threshold
        latency_p95_threshold: Maximum p95 latency in ms
        output_path: Path to save results JSON
        verbose: Enable verbose output
        retrieval_fn: Custom retrieval function

    Returns:
        EvaluationResult
    """
    config = EvaluationConfig(
        golden_set_version=golden_set_version,
        golden_set_path=Path(golden_set_path) if golden_set_path else None,
        mrr_threshold=mrr_threshold,
        latency_p95_threshold=latency_p95_threshold,
        output_path=Path(output_path) if output_path else None,
        verbose=verbose,
    )

    evaluator = RetrievalEvaluator(config, retrieval_fn)
    return await evaluator.run()


def main():
    """CLI entry point for CI integration."""
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument("--version", default="v1", help="Golden set version")
    parser.add_argument("--path", help="Explicit path to golden set JSONL")
    parser.add_argument("--mrr-threshold", type=float, default=0.65, help="MRR@10 threshold")
    parser.add_argument("--latency-threshold", type=float, default=800.0, help="Latency p95 threshold (ms)")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    config = EvaluationConfig(
        golden_set_version=args.version,
        golden_set_path=Path(args.path) if args.path else None,
        mrr_threshold=args.mrr_threshold,
        latency_p95_threshold=args.latency_threshold,
        output_path=Path(args.output) if args.output else None,
        verbose=args.verbose,
    )

    # Run evaluation
    evaluator = RetrievalEvaluator(config)
    result = asyncio.run(evaluator.run())

    # Print summary
    print("\n=== Retrieval Evaluation Results ===")
    print(f"Golden Set Version: {result.config.golden_set_version}")
    print(f"Total Queries: {result.metrics.total_queries}")
    print(f"Duration: {result.duration_seconds:.2f}s")
    print()

    print("MRR@k:")
    for k, v in sorted(result.metrics.mrr_at_k.items()):
        print(f"  @{k}: {v:.4f}")

    print("\nNDCG@k:")
    for k, v in sorted(result.metrics.ndcg_at_k.items()):
        print(f"  @{k}: {v:.4f}")

    print("\nRecall@k:")
    for k, v in sorted(result.metrics.recall_at_k.items()):
        print(f"  @{k}: {v:.4f}")

    print("\nPrecision@k:")
    for k, v in sorted(result.metrics.precision_at_k.items()):
        print(f"  @{k}: {v:.4f}")

    print(f"\nLatency: p50={result.metrics.latency_p50:.2f}ms, "
          f"p95={result.metrics.latency_p95:.2f}ms, "
          f"p99={result.metrics.latency_p99:.2f}ms")

    print("\nThreshold Check:")
    print(f"  MRR@{config.mrr_threshold_k} >= {config.mrr_threshold}: "
          f"{'PASS' if result.metrics.mrr_at_k.get(config.mrr_threshold_k, 0) >= config.mrr_threshold else 'FAIL'}")
    print(f"  Latency p95 <= {config.latency_p95_threshold}ms: "
          f"{'PASS' if result.metrics.latency_p95 <= config.latency_p95_threshold else 'FAIL'}")

    if result.failures:
        print("\nFailures:")
        for failure in result.failures:
            print(f"  - {failure}")

    # Exit with error code if failed (for CI gating)
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
