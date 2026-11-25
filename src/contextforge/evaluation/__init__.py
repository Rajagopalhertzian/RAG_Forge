"""
ContextForge Evaluation Package

Comprehensive evaluation framework for RAG pipelines:
- Retrieval Evaluation (MRR, NDCG, Recall, Precision, Latency)
- Generation Evaluation (RAGAS, Citation Accuracy, Hallucination Detection, LLM Judge)
- Chunking Evaluation (Boundary Preservation, Semantic Coherence)
- Embedding Evaluation (Alignment, Clustering, Retrieval Correlation, Dimensionality)
"""

from contextforge.evaluation.chunking import (
    ChunkingEvaluator,
    create_chunking_evaluator,
)
from contextforge.evaluation.embedding import (
    EmbeddingEvaluator,
    create_embedding_evaluator,
)
from contextforge.evaluation.generation import (
    CustomGenerationEvaluator,
    LLMJudgeEvaluator,
    RAGASEvaluator,
    create_custom_evaluator,
    create_llm_judge,
    create_ragas_evaluator,
)
from contextforge.evaluation.retrieval import (
    AlertLevel,
    EvaluationConfig,
    EvaluationResult,
    GateConfig,
    GateEvaluator,
    GateStatus,
    GoldenDataset,
    GoldenQA,
    RegressionDetector,
    RetrievalEvaluator,
    RetrievalMetrics,
    ThresholdRule,
    check_thresholds,
    evaluate_retrieval,
    load_golden_set,
    run_evaluation,
)

__all__ = [
    # Retrieval
    "RetrievalMetrics",
    "evaluate_retrieval",
    "check_thresholds",
    "GoldenQA",
    "GoldenDataset",
    "load_golden_set",
    "EvaluationConfig",
    "EvaluationResult",
    "RetrievalEvaluator",
    "run_evaluation",
    "ThresholdRule",
    "GateConfig",
    "GateEvaluator",
    "RegressionDetector",
    "AlertLevel",
    "GateStatus",
    # Generation
    "RAGASEvaluator",
    "create_ragas_evaluator",
    "CustomGenerationEvaluator",
    "create_custom_evaluator",
    "LLMJudgeEvaluator",
    "create_llm_judge",
    # Chunking
    "ChunkingEvaluator",
    "create_chunking_evaluator",
    # Embedding
    "EmbeddingEvaluator",
    "create_embedding_evaluator",
]
