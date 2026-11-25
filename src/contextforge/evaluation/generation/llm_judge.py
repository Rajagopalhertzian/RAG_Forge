"""
LLM-as-a-Judge Evaluation

Implements LLM-based evaluation for generation quality:
- Pairwise comparison vs baseline (win rate > 60%)
- Absolute scoring (1-5 scale)
- Supports multiple judge models
"""

from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class JudgeModel(str, Enum):
    """Supported judge models."""

    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    CLAUDE_3_5_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"


class PairwiseResult(BaseModel):
    """Result of pairwise comparison."""

    winner: Literal["A", "B", "tie"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    scores: dict[str, float] = Field(default_factory=dict)  # Detailed criteria scores


class AbsoluteScoreResult(BaseModel):
    """Result of absolute scoring."""

    score: float = Field(ge=1.0, le=5.0)
    criteria_scores: dict[str, float] = Field(default_factory=dict)
    reasoning: str
    passed: bool  # Score >= threshold


class LLMJudgeConfig(BaseModel):
    """Configuration for LLM judge."""

    model: JudgeModel = JudgeModel.GPT_4O_MINI
    temperature: float = 0.0
    max_tokens: int = 1000
    # Pairwise comparison criteria
    pairwise_criteria: list[str] = Field(default_factory=lambda: [
        "accuracy",
        "completeness",
        "clarity",
        "relevance",
        "citation_quality",
    ])
    # Absolute scoring criteria
    absolute_criteria: list[str] = Field(default_factory=lambda: [
        "factual_accuracy",
        "completeness",
        "clarity",
        "relevance",
        "citation_quality",
        "conciseness",
    ])
    # Thresholds
    pairwise_win_threshold: float = 0.60  # Win rate > 60%
    absolute_score_threshold: float = 3.5  # Score >= 3.5/5
    max_concurrent: int = 3


# Prompt templates
PAIRWISE_PROMPT = """You are an expert evaluator comparing two answers to the same question.
Evaluate which answer is better based on the following criteria:
{criteria}

Question: {question}

Answer A:
{answer_a}

Answer B:
{answer_b}

Context (retrieved documents):
{context}

Provide your evaluation in the following JSON format:
{{
    "winner": "A" | "B" | "tie",
    "confidence": 0.0-1.0,
    "reasoning": "Detailed explanation of your decision",
    "scores": {{
        "accuracy": 0.0-1.0,
        "completeness": 0.0-1.0,
        "clarity": 0.0-1.0,
        "relevance": 0.0-1.0,
        "citation_quality": 0.0-1.0
    }}
}}

Important: Be objective. Consider factual accuracy, completeness, clarity, relevance to the question,
and quality of citations/references to the provided context.
"""

ABSOLUTE_PROMPT = """You are an expert evaluator scoring an answer to a question.
Evaluate the answer on a scale of 1-5 based on the following criteria:
{criteria}

Question: {question}

Answer:
{answer}

Context (retrieved documents):
{context}

Provide your evaluation in the following JSON format:
{{
    "score": 1.0-5.0,
    "criteria_scores": {{
        "factual_accuracy": 1.0-5.0,
        "completeness": 1.0-5.0,
        "clarity": 1.0-5.0,
        "relevance": 1.0-5.0,
        "citation_quality": 1.0-5.0,
        "conciseness": 1.0-5.0
    }},
    "reasoning": "Detailed explanation of your scoring"
}}

Scoring Guide:
- 5: Excellent - Fully accurate, complete, clear, well-cited, concise
- 4: Good - Minor issues in one area
- 3: Acceptable - Some gaps or inaccuracies
- 2: Poor - Significant issues, missing key information
- 1: Unacceptable - Factually incorrect or irrelevant
"""


class LLMJudgeClient:
    """
    Client for calling LLM judge models.

    In production, this would use actual API calls to OpenAI/Anthropic.
    For now, provides a mock implementation for testing.
    """

    def __init__(self, config: LLMJudgeConfig = None):
        self.config = config or LLMJudgeConfig()

    async def _call_llm(self, prompt: str) -> str:
        """
        Call the LLM judge model.

        In production, replace with actual API call:
        - OpenAI: client.chat.completions.create(...)
        - Anthropic: client.messages.create(...)

        For now, returns mock response.
        """
        # Simulate API latency
        await asyncio.sleep(0.1)

        # Mock response - in production this would be actual LLM output
        return json.dumps({
            "winner": "A",
            "confidence": 0.85,
            "reasoning": "Answer A provides more accurate information with better citations.",
            "scores": {
                "accuracy": 0.9,
                "completeness": 0.85,
                "clarity": 0.9,
                "relevance": 0.95,
                "citation_quality": 0.8,
            },
        })

    async def pairwise_compare(
        self,
        question: str,
        answer_a: str,
        answer_b: str,
        context: str = "",
    ) -> PairwiseResult:
        """
        Compare two answers pairwise.

        Args:
            question: The question
            answer_a: First answer (candidate)
            answer_b: Second answer (baseline)
            context: Retrieved context for reference

        Returns:
            PairwiseResult
        """
        criteria_text = "\n".join(f"- {c}: {self._criterion_description(c)}"
                                   for c in self.config.pairwise_criteria)

        prompt = PAIRWISE_PROMPT.format(
            criteria=criteria_text,
            question=question,
            answer_a=answer_a,
            answer_b=answer_b,
            context=context[:3000] if context else "No context provided",
        )

        response = await self._call_llm(prompt)

        try:
            data = json.loads(response)
            return PairwiseResult(**data)
        except (json.JSONDecodeError, Exception) as e:
            # Fallback on parse error
            return PairwiseResult(
                winner="tie",
                confidence=0.5,
                reasoning=f"Parse error: {e}",
            )

    async def absolute_score(
        self,
        question: str,
        answer: str,
        context: str = "",
    ) -> AbsoluteScoreResult:
        """
        Score a single answer absolutely.

        Args:
            question: The question
            answer: The answer to score
            context: Retrieved context for reference

        Returns:
            AbsoluteScoreResult
        """
        criteria_text = "\n".join(f"- {c}: {self._criterion_description(c)}"
                                   for c in self.config.absolute_criteria)

        prompt = ABSOLUTE_PROMPT.format(
            criteria=criteria_text,
            question=question,
            answer=answer,
            context=context[:3000] if context else "No context provided",
        )

        response = await self._call_llm(prompt)

        try:
            data = json.loads(response)
            score = data.get("score", 3.0)
            return AbsoluteScoreResult(
                score=score,
                criteria_scores=data.get("criteria_scores", {}),
                reasoning=data.get("reasoning", ""),
                passed=score >= self.config.absolute_score_threshold,
            )
        except (json.JSONDecodeError, Exception) as e:
            return AbsoluteScoreResult(
                score=3.0,
                criteria_scores={},
                reasoning=f"Parse error: {e}",
                passed=False,
            )

    def _criterion_description(self, criterion: str) -> str:
        """Get description for a criterion."""
        descriptions = {
            "accuracy": "Factual correctness of the information",
            "completeness": "Whether all aspects of the question are addressed",
            "clarity": "How clear and understandable the answer is",
            "relevance": "How directly the answer addresses the question",
            "citation_quality": "Quality and accuracy of citations to source documents",
            "factual_accuracy": "Correctness of facts and claims",
            "conciseness": "Whether the answer is appropriately concise",
        }
        return descriptions.get(criterion, "")


class PairwiseEvaluator:
    """
    Runs pairwise evaluation between candidate and baseline answers.
    """

    def __init__(self, config: LLMJudgeConfig = None):
        self.config = config or LLMJudgeConfig()
        self.client = LLMJudgeClient(self.config)

    async def evaluate(
        self,
        question: str,
        candidate_answer: str,
        baseline_answer: str,
        context: str = "",
    ) -> PairwiseResult:
        """
        Run single pairwise evaluation.

        Args:
            question: The question
            candidate_answer: New answer to evaluate
            baseline_answer: Baseline answer to compare against
            context: Retrieved context

        Returns:
            PairwiseResult
        """
        # Run comparison both ways to reduce position bias
        result_ab = await self.client.pairwise_compare(
            question, candidate_answer, baseline_answer, context
        )
        result_ba = await self.client.pairwise_compare(
            question, baseline_answer, candidate_answer, context
        )

        # Check for consistency
        if result_ab.winner == "A" and result_ba.winner == "B":
            # Consistent: candidate wins both
            return result_ab
        elif result_ab.winner == "B" and result_ba.winner == "A":
            # Consistent: baseline wins both
            return result_ba
        elif result_ab.winner == "tie" or result_ba.winner == "tie":
            # One or both are ties
            return PairwiseResult(
                winner="tie",
                confidence=(result_ab.confidence + result_ba.confidence) / 2,
                reasoning=f"Mixed results: A vs B: {result_ab.winner}, B vs A: {result_ba.winner}",
            )
        else:
            # Inconsistent - default to tie
            return PairwiseResult(
                winner="tie",
                confidence=0.5,
                reasoning="Inconsistent pairwise results",
            )

    async def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[PairwiseResult]:
        """
        Evaluate multiple pairwise comparisons.

        Args:
            samples: List of dicts with keys: question, candidate_answer, baseline_answer, context

        Returns:
            List of PairwiseResult
        """
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def eval_one(sample):
            async with semaphore:
                return await self.evaluate(
                    question=sample["question"],
                    candidate_answer=sample["candidate_answer"],
                    baseline_answer=sample["baseline_answer"],
                    context=sample.get("context", ""),
                )

        tasks = [eval_one(s) for s in samples]
        return await asyncio.gather(*tasks)

    def calculate_win_rate(self, results: list[PairwiseResult]) -> float:
        """Calculate candidate win rate from results."""
        if not results:
            return 0.0

        wins = sum(1 for r in results if r.winner == "A")
        ties = sum(1 for r in results if r.winner == "tie")
        # Count ties as half win
        return (wins + 0.5 * ties) / len(results)


class AbsoluteEvaluator:
    """
    Runs absolute scoring evaluation.
    """

    def __init__(self, config: LLMJudgeConfig = None):
        self.config = config or LLMJudgeConfig()
        self.client = LLMJudgeClient(self.config)

    async def evaluate(
        self,
        question: str,
        answer: str,
        context: str = "",
    ) -> AbsoluteScoreResult:
        """Run single absolute evaluation."""
        return await self.client.absolute_score(question, answer, context)

    async def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[AbsoluteScoreResult]:
        """Evaluate multiple samples."""
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def eval_one(sample):
            async with semaphore:
                return await self.evaluate(
                    question=sample["question"],
                    answer=sample["answer"],
                    context=sample.get("context", ""),
                )

        tasks = [eval_one(s) for s in samples]
        return await asyncio.gather(*tasks)

    def calculate_pass_rate(self, results: list[AbsoluteScoreResult]) -> float:
        """Calculate pass rate (score >= threshold)."""
        if not results:
            return 0.0
        return sum(1 for r in results if r.passed) / len(results)

    def calculate_average_score(self, results: list[AbsoluteScoreResult]) -> float:
        """Calculate average score."""
        if not results:
            return 0.0
        return sum(r.score for r in results) / len(results)


class LLMJudgeEvaluator:
    """
    Combined LLM judge evaluator supporting both pairwise and absolute modes.
    """

    def __init__(self, config: LLMJudgeConfig = None):
        self.config = config or LLMJudgeConfig()
        self.pairwise = PairwiseEvaluator(self.config)
        self.absolute = AbsoluteEvaluator(self.config)

    async def evaluate_pairwise(
        self,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Run pairwise evaluation on batch.

        Returns:
            Dict with results, win_rate, and pass/fail
        """
        results = await self.pairwise.evaluate_batch(samples)
        win_rate = self.pairwise.calculate_win_rate(results)

        return {
            "results": [r.model_dump() for r in results],
            "win_rate": win_rate,
            "passed": win_rate >= self.config.pairwise_win_threshold,
            "threshold": self.config.pairwise_win_threshold,
            "total_samples": len(samples),
            "wins": sum(1 for r in results if r.winner == "A"),
            "losses": sum(1 for r in results if r.winner == "B"),
            "ties": sum(1 for r in results if r.winner == "tie"),
        }

    async def evaluate_absolute(
        self,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Run absolute scoring on batch.

        Returns:
            Dict with results, average_score, pass_rate, and pass/fail
        """
        results = await self.absolute.evaluate_batch(samples)
        avg_score = self.absolute.calculate_average_score(results)
        pass_rate = self.absolute.calculate_pass_rate(results)

        return {
            "results": [r.model_dump() for r in results],
            "average_score": avg_score,
            "pass_rate": pass_rate,
            "passed": avg_score >= self.config.absolute_score_threshold,
            "score_threshold": self.config.absolute_score_threshold,
            "pass_threshold": self.config.absolute_score_threshold,
            "total_samples": len(samples),
        }


def create_llm_judge(
    model: JudgeModel = JudgeModel.GPT_4O_MINI,
    pairwise_win_threshold: float = 0.60,
    absolute_score_threshold: float = 3.5,
) -> LLMJudgeEvaluator:
    """Create LLM judge evaluator with custom config."""
    config = LLMJudgeConfig(
        model=model,
        pairwise_win_threshold=pairwise_win_threshold,
        absolute_score_threshold=absolute_score_threshold,
    )
    return LLMJudgeEvaluator(config)
