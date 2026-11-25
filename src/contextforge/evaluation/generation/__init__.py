"""
Generation Evaluation Package

Provides RAGAS metrics, custom citation/hallucination evaluation, and LLM-as-a-judge
for generation quality evaluation.
"""

from contextforge.evaluation.generation.custom import (
    CITATION_ACCURACY_THRESHOLD,
    HALLUCINATION_RATE_THRESHOLD,
    CitationAccuracyEvaluator,
    CitationAccuracyResult,
    ClaimExtractionResult,
    ClaimExtractor,
    CustomEvaluatorConfig,
    CustomGenerationEvaluator,
    HallucinationDetector,
    HallucinationResult,
    create_custom_evaluator,
)
from contextforge.evaluation.generation.llm_judge import (
    AbsoluteEvaluator,
    AbsoluteScoreResult,
    JudgeModel,
    LLMJudgeClient,
    LLMJudgeConfig,
    LLMJudgeEvaluator,
    PairwiseEvaluator,
    PairwiseResult,
    create_llm_judge,
)
from contextforge.evaluation.generation.ragas import (
    ANSWER_RELEVANCY_THRESHOLD,
    CONTEXT_PRECISION_THRESHOLD,
    CONTEXT_RECALL_THRESHOLD,
    FAITHFULNESS_THRESHOLD,
    AnswerRelevancyEvaluator,
    ContextPrecisionEvaluator,
    ContextRecallEvaluator,
    FaithfulnessEvaluator,
    RAGASConfig,
    RAGASEvaluationResult,
    RAGASEvaluator,
    RAGASMetricResult,
    create_ragas_evaluator,
)

__all__ = [
    # RAGAS
    "RAGASConfig",
    "RAGASMetricResult",
    "RAGASEvaluationResult",
    "FaithfulnessEvaluator",
    "AnswerRelevancyEvaluator",
    "ContextPrecisionEvaluator",
    "ContextRecallEvaluator",
    "RAGASEvaluator",
    "create_ragas_evaluator",
    "FAITHFULNESS_THRESHOLD",
    "ANSWER_RELEVANCY_THRESHOLD",
    "CONTEXT_PRECISION_THRESHOLD",
    "CONTEXT_RECALL_THRESHOLD",
    # Custom
    "CustomEvaluatorConfig",
    "CitationAccuracyResult",
    "HallucinationResult",
    "ClaimExtractionResult",
    "ClaimExtractor",
    "CitationAccuracyEvaluator",
    "HallucinationDetector",
    "CustomGenerationEvaluator",
    "create_custom_evaluator",
    "HALLUCINATION_RATE_THRESHOLD",
    "CITATION_ACCURACY_THRESHOLD",
    # LLM Judge
    "LLMJudgeConfig",
    "PairwiseResult",
    "AbsoluteScoreResult",
    "JudgeModel",
    "LLMJudgeClient",
    "PairwiseEvaluator",
    "AbsoluteEvaluator",
    "LLMJudgeEvaluator",
    "create_llm_judge",
]
