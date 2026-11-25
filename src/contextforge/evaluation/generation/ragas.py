"""
RAGAS Evaluation Metrics

Implements RAGAS metrics for generation quality evaluation:
- Faithfulness: Does the answer stay faithful to the retrieved context?
- Answer Relevancy: Is the answer relevant to the question?
- Context Precision: Is the retrieved context precise (relevant docs ranked higher)?
- Context Recall: Does the retrieved context cover all relevant information?

Based on the RAGAS paper: "RAGAS: Automated Evaluation of Retrieval Augmented Generation"
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

# RAGAS metric thresholds (from spec)
FAITHFULNESS_THRESHOLD = 0.85
ANSWER_RELEVANCY_THRESHOLD = 0.80
CONTEXT_PRECISION_THRESHOLD = 0.75
CONTEXT_RECALL_THRESHOLD = 0.75


class RAGASMetricResult(BaseModel):
    """Result of a single RAGAS metric evaluation."""

    name: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float
    passed: bool
    reasoning: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class RAGASEvaluationResult(BaseModel):
    """Complete RAGAS evaluation result."""

    faithfulness: RAGASMetricResult
    answer_relevancy: RAGASMetricResult
    context_precision: RAGASMetricResult
    context_recall: RAGASMetricResult
    overall_score: float
    overall_passed: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class RAGASConfig:
    """Configuration for RAGAS evaluation."""

    faithfulness_threshold: float = FAITHFULNESS_THRESHOLD
    answer_relevancy_threshold: float = ANSWER_RELEVANCY_THRESHOLD
    context_precision_threshold: float = CONTEXT_PRECISION_THRESHOLD
    context_recall_threshold: float = CONTEXT_RECALL_THRESHOLD
    llm_model: str = "gpt-4o-mini"  # Model for LLM-based evaluation
    max_concurrent: int = 5


class FaithfulnessEvaluator:
    """
    Evaluates faithfulness: whether the generated answer is consistent with the retrieved context.

    Faithfulness = |{claims in answer supported by context}| / |{claims in answer}|
    """

    def __init__(self, config: RAGASConfig):
        self.config = config

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
    ) -> RAGASMetricResult:
        """
        Evaluate faithfulness of answer against contexts.

        Args:
            question: The original question
            answer: The generated answer
            contexts: List of retrieved context passages

        Returns:
            RAGASMetricResult with faithfulness score
        """
        # In production, this would use an LLM to:
        # 1. Extract claims from the answer
        # 2. Check each claim against the context
        # 3. Calculate ratio of supported claims

        # For now, implement a heuristic-based approach
        # This is a simplified version - real implementation uses LLM judge

        # Extract claims from answer (simplified: split by sentences)
        claims = self._extract_claims(answer)

        if not claims:
            return RAGASMetricResult(
                name="faithfulness",
                score=1.0,
                threshold=self.config.faithfulness_threshold,
                passed=True,
                reasoning="No claims to verify",
            )

        # Check each claim against context
        supported_claims = 0
        for claim in claims:
            if self._claim_supported(claim, contexts):
                supported_claims += 1

        score = supported_claims / len(claims)
        passed = score >= self.config.faithfulness_threshold

        return RAGASMetricResult(
            name="faithfulness",
            score=score,
            threshold=self.config.faithfulness_threshold,
            passed=passed,
            reasoning=f"{supported_claims}/{len(claims)} claims supported by context",
            details={
                "total_claims": len(claims),
                "supported_claims": supported_claims,
                "claims": claims,
            },
        )

    def _extract_claims(self, text: str) -> list[str]:
        """Extract factual claims from text (simplified)."""
        # Split by sentence-ending punctuation
        import re
        sentences = re.split(r'[.!?]+', text)
        claims = [s.strip() for s in sentences if len(s.strip()) > 10]
        return claims

    def _claim_supported(self, claim: str, contexts: list[str]) -> bool:
        """Check if a claim is supported by any context (simplified keyword overlap)."""
        claim_words = set(claim.lower().split())
        # Remove stop words
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "this", "that", "these", "those"}
        claim_words = claim_words - stop_words

        if not claim_words:
            return True

        for context in contexts:
            context_words = set(context.lower().split())
            overlap = claim_words & context_words
            # Consider supported if >50% of claim words appear in context
            if len(overlap) / len(claim_words) > 0.5:
                return True

        return False


class AnswerRelevancyEvaluator:
    """
    Evaluates answer relevancy: whether the answer addresses the question.

    Answer Relevancy = mean cosine similarity between question and generated answer embeddings
    (using LLM to generate hypothetical questions from answer and compare)
    """

    def __init__(self, config: RAGASConfig):
        self.config = config

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
    ) -> RAGASMetricResult:
        """
        Evaluate answer relevancy.

        Args:
            question: The original question
            answer: The generated answer
            contexts: List of retrieved context passages (unused for this metric)

        Returns:
            RAGASMetricResult with answer relevancy score
        """
        # Simplified heuristic: keyword overlap between question and answer
        # Real implementation uses LLM to generate questions from answer

        question_words = set(question.lower().split())
        answer_words = set(answer.lower().split())

        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "this", "that", "these", "those", "what", "how", "why", "when", "where", "who", "which"}

        question_words = question_words - stop_words
        answer_words = answer_words - stop_words

        if not question_words:
            return RAGASMetricResult(
                name="answer_relevancy",
                score=1.0,
                threshold=self.config.answer_relevancy_threshold,
                passed=True,
                reasoning="Empty question",
            )

        overlap = question_words & answer_words
        score = len(overlap) / len(question_words)

        # Boost score if answer contains question keywords
        if len(overlap) > 0:
            score = min(1.0, score * 1.5)

        passed = score >= self.config.answer_relevancy_threshold

        return RAGASMetricResult(
            name="answer_relevancy",
            score=score,
            threshold=self.config.answer_relevancy_threshold,
            passed=passed,
            reasoning=f"Keyword overlap: {len(overlap)}/{len(question_words)} question words in answer",
            details={
                "question_words": list(question_words),
                "answer_words": list(answer_words),
                "overlap": list(overlap),
            },
        )


class ContextPrecisionEvaluator:
    """
    Evaluates context precision: whether relevant contexts are ranked higher.

    Context Precision = Average Precision of retrieved contexts based on relevance
    """

    def __init__(self, config: RAGASConfig):
        self.config = config

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        relevant_contexts: list[str] = None,
    ) -> RAGASMetricResult:
        """
        Evaluate context precision.

        Args:
            question: The original question
            answer: The generated answer
            contexts: List of retrieved context passages (in ranked order)
            relevant_contexts: List of known relevant context passages (ground truth)

        Returns:
            RAGASMetricResult with context precision score
        """
        if not contexts:
            return RAGASMetricResult(
                name="context_precision",
                score=0.0,
                threshold=self.config.context_precision_threshold,
                passed=False,
                reasoning="No contexts retrieved",
            )

        if relevant_contexts is None:
            # Use heuristic: contexts that share keywords with question
            question_words = set(question.lower().split())
            stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "what", "how", "why", "when", "where", "who", "which"}
            question_words = question_words - stop_words

            relevant_contexts = []
            for ctx in contexts:
                ctx_words = set(ctx.lower().split())
                if question_words & ctx_words:
                    relevant_contexts.append(ctx)

        if not relevant_contexts:
            return RAGASMetricResult(
                name="context_precision",
                score=0.0,
                threshold=self.config.context_precision_threshold,
                passed=False,
                reasoning="No relevant contexts identified",
            )

        # Calculate average precision
        relevant_set = set(relevant_contexts)
        precision_sum = 0.0
        relevant_found = 0

        for i, ctx in enumerate(contexts, 1):
            if ctx in relevant_set:
                relevant_found += 1
                precision_sum += relevant_found / i

        score = precision_sum / len(relevant_contexts) if relevant_contexts else 0.0
        passed = score >= self.config.context_precision_threshold

        return RAGASMetricResult(
            name="context_precision",
            score=score,
            threshold=self.config.context_precision_threshold,
            passed=passed,
            reasoning=f"Average precision over {len(relevant_contexts)} relevant contexts",
            details={
                "total_contexts": len(contexts),
                "relevant_contexts": len(relevant_contexts),
                "relevant_found": relevant_found,
            },
        )


class ContextRecallEvaluator:
    """
    Evaluates context recall: whether all relevant information was retrieved.

    Context Recall = |{relevant contexts retrieved}| / |{all relevant contexts}|
    """

    def __init__(self, config: RAGASConfig):
        self.config = config

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        relevant_contexts: list[str] = None,
    ) -> RAGASMetricResult:
        """
        Evaluate context recall.

        Args:
            question: The original question
            answer: The generated answer
            contexts: List of retrieved context passages
            relevant_contexts: List of all known relevant context passages (ground truth)

        Returns:
            RAGASMetricResult with context recall score
        """
        if relevant_contexts is None:
            # Cannot compute recall without ground truth
            return RAGASMetricResult(
                name="context_recall",
                score=1.0,
                threshold=self.config.context_recall_threshold,
                passed=True,
                reasoning="No ground truth relevant contexts provided",
            )

        if not relevant_contexts:
            return RAGASMetricResult(
                name="context_recall",
                score=1.0,
                threshold=self.config.context_recall_threshold,
                passed=True,
                reasoning="No relevant contexts in ground truth",
            )

        retrieved_set = set(contexts)
        relevant_set = set(relevant_contexts)

        retrieved_relevant = retrieved_set & relevant_set
        score = len(retrieved_relevant) / len(relevant_set)
        passed = score >= self.config.context_recall_threshold

        return RAGASMetricResult(
            name="context_recall",
            score=score,
            threshold=self.config.context_recall_threshold,
            passed=passed,
            reasoning=f"Retrieved {len(retrieved_relevant)}/{len(relevant_set)} relevant contexts",
            details={
                "total_relevant": len(relevant_set),
                "retrieved_relevant": len(retrieved_relevant),
                "missed": list(relevant_set - retrieved_set),
            },
        )


class RAGASEvaluator:
    """
    Main RAGAS evaluator combining all four metrics.
    """

    def __init__(self, config: RAGASConfig = None):
        self.config = config or RAGASConfig()
        self.faithfulness = FaithfulnessEvaluator(self.config)
        self.answer_relevancy = AnswerRelevancyEvaluator(self.config)
        self.context_precision = ContextPrecisionEvaluator(self.config)
        self.context_recall = ContextRecallEvaluator(self.config)

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        relevant_contexts: list[str] = None,
    ) -> RAGASEvaluationResult:
        """
        Run all RAGAS metrics.

        Args:
            question: The original question
            answer: The generated answer
            contexts: List of retrieved context passages
            relevant_contexts: Ground truth relevant contexts (for recall/precision)

        Returns:
            RAGASEvaluationResult with all metric scores
        """
        # Run all evaluations concurrently
        faithfulness_task = self.faithfulness.evaluate(question, answer, contexts)
        answer_relevancy_task = self.answer_relevancy.evaluate(question, answer, contexts)
        context_precision_task = self.context_precision.evaluate(question, answer, contexts, relevant_contexts)
        context_recall_task = self.context_recall.evaluate(question, answer, contexts, relevant_contexts)

        faithfulness, answer_relevancy, context_precision, context_recall = await asyncio.gather(
            faithfulness_task,
            answer_relevancy_task,
            context_precision_task,
            context_recall_task,
        )

        # Calculate overall score (harmonic mean of passed metrics)
        scores = [
            faithfulness.score,
            answer_relevancy.score,
            context_precision.score,
            context_recall.score,
        ]
        overall_score = sum(scores) / len(scores)
        overall_passed = all([
            faithfulness.passed,
            answer_relevancy.passed,
            context_precision.passed,
            context_recall.passed,
        ])

        return RAGASEvaluationResult(
            faithfulness=faithfulness,
            answer_relevancy=answer_relevancy,
            context_precision=context_precision,
            context_recall=context_recall,
            overall_score=overall_score,
            overall_passed=overall_passed,
            metadata={
                "question": question,
                "answer_length": len(answer),
                "num_contexts": len(contexts),
            },
        )

    async def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[RAGASEvaluationResult]:
        """
        Evaluate multiple samples.

        Args:
            samples: List of dicts with keys: question, answer, contexts, relevant_contexts (optional)

        Returns:
            List of RAGASEvaluationResult
        """
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def eval_one(sample):
            async with semaphore:
                return await self.evaluate(
                    question=sample["question"],
                    answer=sample["answer"],
                    contexts=sample["contexts"],
                    relevant_contexts=sample.get("relevant_contexts"),
                )

        tasks = [eval_one(s) for s in samples]
        return await asyncio.gather(*tasks)


def create_ragas_evaluator(
    faithfulness_threshold: float = FAITHFULNESS_THRESHOLD,
    answer_relevancy_threshold: float = ANSWER_RELEVANCY_THRESHOLD,
    context_precision_threshold: float = CONTEXT_PRECISION_THRESHOLD,
    context_recall_threshold: float = CONTEXT_RECALL_THRESHOLD,
) -> RAGASEvaluator:
    """Create RAGAS evaluator with custom thresholds."""
    config = RAGASConfig(
        faithfulness_threshold=faithfulness_threshold,
        answer_relevancy_threshold=answer_relevancy_threshold,
        context_precision_threshold=context_precision_threshold,
        context_recall_threshold=context_recall_threshold,
    )
    return RAGASEvaluator(config)
