"""
Retrieval Evaluation Package

Provides metrics, dataset management, CI runner, and threshold gating
for retrieval quality evaluation.
"""

from contextforge.evaluation.retrieval.dataset import (
    GOLDEN_QA_SCHEMA,
    GoldenDataset,
    GoldenQA,
    list_available_versions,
    load_golden_set,
)
from contextforge.evaluation.retrieval.metrics import (
    RetrievalMetrics,
    calculate_latency_percentiles,
    check_thresholds,
    evaluate_retrieval,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from contextforge.evaluation.retrieval.runner import (
    EvaluationConfig,
    EvaluationResult,
    RetrievalEvaluator,
    run_evaluation,
)
from contextforge.evaluation.retrieval.thresholds import (
    AlertLevel,
    GateConfig,
    GateEvaluator,
    GateResult,
    GateStatus,
    RegressionAlert,
    RegressionDetector,
    ThresholdRule,
    create_ci_gate_config,
    create_default_gate_config,
    create_nightly_gate_config,
)

__all__ = [
    # Metrics
    "RetrievalMetrics",
    "evaluate_retrieval",
    "check_thresholds",
    "reciprocal_rank",
    "ndcg_at_k",
    "recall_at_k",
    "precision_at_k",
    "calculate_latency_percentiles",
    # Dataset
    "GoldenQA",
    "GoldenDataset",
    "load_golden_set",
    "list_available_versions",
    "GOLDEN_QA_SCHEMA",
    # Runner
    "EvaluationConfig",
    "EvaluationResult",
    "RetrievalEvaluator",
    "run_evaluation",
    # Thresholds
    "ThresholdRule",
    "GateConfig",
    "GateResult",
    "GateEvaluator",
    "RegressionDetector",
    "RegressionAlert",
    "AlertLevel",
    "GateStatus",
    "create_default_gate_config",
    "create_ci_gate_config",
    "create_nightly_gate_config",
]
