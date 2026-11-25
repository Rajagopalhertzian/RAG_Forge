"""
Tests for Generation Evaluation Pipeline

Tests cover:
- RAGAS metrics (faithfulness, answer_relevancy, context_precision, context_recall)
- Custom citation accuracy and hallucination detection
- LLM Judge pairwise comparison and absolute scoring
"""

import json
import tempfile
from unittest.mock import patch

import pytest

from contextforge.evaluation.generation.custom import (
    CitationAccuracyResult,
    CustomGenerationEvaluator,
    HallucinationResult,
    evaluate_citation_accuracy,
    evaluate_hallucination_rate,
)
from contextforge.evaluation.generation.llm_judge import (
    AbsoluteScoreResult,
    JudgeConfig,
    LLMJudgeEvaluator,
    PairwiseResult,
)
from contextforge.evaluation.generation.ragas import (
    RAGASConfig,
    RAGASEvaluator,
    RAGASResult,
    evaluate_answer_relevancy,
    evaluate_context_precision,
    evaluate_context_recall,
    evaluate_faithfulness,
)


class TestRAGASMetrics:
    """Test individual RAGAS metric functions."""

    @pytest.fixture
    def sample_context(self):
        return [
            "Paris is the capital of France.",
            "France is a country in Europe.",
            "The Eiffel Tower is in Paris."
        ]

    @pytest.fixture
    def sample_answer_faithful(self):
        return "Paris is the capital of France."

    @pytest.fixture
    def sample_answer_unfaithful(self):
        return "Paris is the capital of Germany."

    @pytest.fixture
    def sample_question(self):
        return "What is the capital of France?"

    def test_evaluate_faithfulness_faithful(self, sample_context, sample_answer_faithful, sample_question):
        """Test faithfulness evaluation with faithful answer."""
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_faithfulness') as mock_llm:
            mock_llm.return_value = {"score": 1.0, "reasoning": "All claims supported by context"}
            score = evaluate_faithfulness(sample_answer_faithful, sample_context, sample_question)
            assert score == 1.0

    def test_evaluate_faithfulness_unfaithful(self, sample_context, sample_answer_unfaithful, sample_question):
        """Test faithfulness evaluation with unfaithful answer."""
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_faithfulness') as mock_llm:
            mock_llm.return_value = {"score": 0.0, "reasoning": "Claim contradicts context"}
            score = evaluate_faithfulness(sample_answer_unfaithful, sample_context, sample_question)
            assert score == 0.0

    def test_evaluate_answer_relevancy_relevant(self, sample_question):
        """Test answer relevancy with relevant answer."""
        answer = "Paris is the capital city of France, located in Europe."
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_relevancy') as mock_llm:
            mock_llm.return_value = {"score": 0.95, "reasoning": "Directly answers the question"}
            score = evaluate_answer_relevancy(answer, sample_question)
            assert score == 0.95

    def test_evaluate_answer_relevancy_irrelevant(self, sample_question):
        """Test answer relevancy with irrelevant answer."""
        answer = "The weather is nice today."
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_relevancy') as mock_llm:
            mock_llm.return_value = {"score": 0.1, "reasoning": "Does not answer the question"}
            score = evaluate_answer_relevancy(answer, sample_question)
            assert score == 0.1

    def test_evaluate_context_precision_high(self, sample_question, sample_context):
        """Test context precision with high precision context."""
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_context_precision') as mock_llm:
            mock_llm.return_value = {"score": 0.9, "reasoning": "Most context is relevant"}
            score = evaluate_context_precision(sample_question, sample_context)
            assert score == 0.9

    def test_evaluate_context_recall_high(self, sample_question, sample_context):
        """Test context recall with high recall context."""
        with patch('contextforge.evaluation.generation.ragas._call_llm_for_context_recall') as mock_llm:
            mock_llm.return_value = {"score": 0.85, "reasoning": "Context covers key information"}
            score = evaluate_context_recall(sample_question, sample_context)
            assert score == 0.85


class TestRAGASEvaluator:
    """Test the RAGASEvaluator class."""

    @pytest.fixture
    def ragas_config(self):
        return RAGASConfig(
            model="gpt-4o",
            batch_size=5,
            thresholds={
                "faithfulness": 0.85,
                "answer_relevancy": 0.80,
                "context_precision": 0.75,
                "context_recall": 0.70,
            }
        )

    @pytest.fixture
    def sample_dataset(self):
        """Create a sample dataset for testing."""
        data = [
            {
                "question": "What is the capital of France?",
                "answer": "Paris is the capital of France.",
                "contexts": [
                    "Paris is the capital of France.",
                    "France is a country in Europe."
                ],
                "ground_truth": "Paris is the capital of France."
            },
            {
                "question": "Who wrote 1984?",
                "answer": "George Orwell wrote 1984.",
                "contexts": [
                    "1984 is a novel by George Orwell.",
                    "George Orwell was a British author."
                ],
                "ground_truth": "George Orwell wrote 1984."
            }
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
            return f.name

    def test_evaluate_dataset(self, ragas_config, sample_dataset):
        """Test evaluating a full dataset."""
        evaluator = RAGASEvaluator(ragas_config)

        with patch.object(evaluator, '_evaluate_single') as mock_eval:
            mock_eval.side_effect = [
                RAGASResult(
                    question="What is the capital of France?",
                    faithfulness=0.95,
                    answer_relevancy=0.90,
                    context_precision=0.85,
                    context_recall=0.80,
                ),
                RAGASResult(
                    question="Who wrote 1984?",
                    faithfulness=0.90,
                    answer_relevancy=0.85,
                    context_precision=0.80,
                    context_recall=0.75,
                ),
            ]

            results = evaluator.evaluate_dataset(sample_dataset)

            assert len(results) == 2
            assert all(isinstance(r, RAGASResult) for r in results)

    def test_aggregate_results(self, ragas_config):
        """Test aggregating multiple RAGAS results."""
        evaluator = RAGASEvaluator(ragas_config)

        results = [
            RAGASResult(
                question="Q1",
                faithfulness=0.9,
                answer_relevancy=0.85,
                context_precision=0.8,
                context_recall=0.75,
            ),
            RAGASResult(
                question="Q2",
                faithfulness=0.8,
                answer_relevancy=0.75,
                context_precision=0.7,
                context_recall=0.65,
            ),
        ]

        aggregated = evaluator.aggregate_results(results)

        assert aggregated["faithfulness"] == 0.85
        assert aggregated["answer_relevancy"] == 0.80
        assert aggregated["context_precision"] == 0.75
        assert aggregated["context_recall"] == 0.70

    def test_check_thresholds_pass(self, ragas_config):
        """Test threshold checking when all pass."""
        evaluator = RAGASEvaluator(ragas_config)

        aggregated = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }

        passed, failures = evaluator.check_thresholds(aggregated)

        assert passed is True
        assert len(failures) == 0

    def test_check_thresholds_fail(self, ragas_config):
        """Test threshold checking when some fail."""
        evaluator = RAGASEvaluator(ragas_config)

        aggregated = {
            "faithfulness": 0.70,  # Below 0.85
            "answer_relevancy": 0.85,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }

        passed, failures = evaluator.check_thresholds(aggregated)

        assert passed is False
        assert any("faithfulness" in f for f in failures)


class TestCitationAccuracy:
    """Test citation accuracy evaluation."""

    @pytest.fixture
    def answer_with_citations(self):
        return "Paris is the capital of France [1]. It is located in Europe [2]."

    @pytest.fixture
    def answer_without_citations(self):
        return "Paris is the capital of France. It is located in Europe."

    @pytest.fixture
    def answer_with_wrong_citations(self):
        return "Paris is the capital of Germany [1]. It is located in Asia [2]."

    @pytest.fixture
    def source_documents(self):
        return [
            "Paris is the capital of France.",
            "France is a country in Europe.",
        ]

    def test_evaluate_citation_accuracy_perfect(self, answer_with_citations, source_documents):
        """Test citation accuracy with perfect citations."""
        with patch('contextforge.evaluation.generation.custom._call_llm_for_citations') as mock_llm:
            mock_llm.return_value = {
                "score": 1.0,
                "details": "All claims properly cited",
                "citation_coverage": 1.0,
                "citation_precision": 1.0,
            }
            result = evaluate_citation_accuracy(answer_with_citations, source_documents)

            assert isinstance(result, CitationAccuracyResult)
            assert result.score == 1.0
            assert result.citation_coverage == 1.0

    def test_evaluate_citation_accuracy_no_citations(self, answer_without_citations, source_documents):
        """Test citation accuracy with no citations."""
        with patch('contextforge.evaluation.generation.custom._call_llm_for_citations') as mock_llm:
            mock_llm.return_value = {
                "score": 0.0,
                "details": "No citations found",
                "citation_coverage": 0.0,
                "citation_precision": 0.0,
            }
            result = evaluate_citation_accuracy(answer_without_citations, source_documents)

            assert result.score == 0.0
            assert result.citation_coverage == 0.0

    def test_evaluate_citation_accuracy_wrong_citations(self, answer_with_wrong_citations, source_documents):
        """Test citation accuracy with incorrect citations."""
        with patch('contextforge.evaluation.generation.custom._call_llm_for_citations') as mock_llm:
            mock_llm.return_value = {
                "score": 0.3,
                "details": "Citations reference incorrect information",
                "citation_coverage": 0.5,
                "citation_precision": 0.2,
            }
            result = evaluate_citation_accuracy(answer_with_wrong_citations, source_documents)

            assert result.score < 0.5


class TestHallucinationDetection:
    """Test hallucination rate evaluation."""

    @pytest.fixture
    def factual_answer(self):
        return "Paris is the capital of France. It has a population of about 2.1 million."

    @pytest.fixture
    def hallucinated_answer(self):
        return "Paris is the capital of France. It has a population of 50 million and is located on the moon."

    @pytest.fixture
    def source_documents(self):
        return [
            "Paris is the capital of France.",
            "Paris has a population of approximately 2.1 million people.",
            "Paris is located in northern France."
        ]

    def test_evaluate_hallucination_rate_factual(self, factual_answer, source_documents):
        """Test hallucination detection with factual answer."""
        with patch('contextforge.evaluation.generation.custom._call_llm_for_hallucination') as mock_llm:
            mock_llm.return_value = {
                "score": 0.0,
                "details": "No hallucinations detected",
                "hallucinated_claims": [],
                "verified_claims": 2,
            }
            result = evaluate_hallucination_rate(factual_answer, source_documents)

            assert isinstance(result, HallucinationResult)
            assert result.score == 0.0
            assert len(result.hallucinated_claims) == 0

    def test_evaluate_hallucination_rate_hallucinated(self, hallucinated_answer, source_documents):
        """Test hallucination detection with hallucinated answer."""
        with patch('contextforge.evaluation.generation.custom._call_llm_for_hallucination') as mock_llm:
            mock_llm.return_value = {
                "score": 0.8,
                "details": "Multiple hallucinated claims detected",
                "hallucinated_claims": [
                    "Population of 50 million",
                    "Located on the moon"
                ],
                "verified_claims": 1,
            }
            result = evaluate_hallucination_rate(hallucinated_answer, source_documents)

            assert result.score > 0.5
            assert len(result.hallucinated_claims) == 2


class TestCustomGenerationEvaluator:
    """Test the CustomGenerationEvaluator class."""

    @pytest.fixture
    def custom_evaluator(self):
        return CustomGenerationEvaluator(
            model="gpt-4o",
            citation_threshold=0.95,
            hallucination_threshold=0.05,
        )

    @pytest.fixture
    def sample_dataset(self):
        data = [
            {
                "question": "What is the capital of France?",
                "answer": "Paris is the capital of France [1].",
                "contexts": ["Paris is the capital of France."],
            },
            {
                "question": "Who wrote 1984?",
                "answer": "George Orwell wrote 1984 [1].",
                "contexts": ["1984 is a novel by George Orwell."],
            }
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
            return f.name

    def test_evaluate_dataset(self, custom_evaluator, sample_dataset):
        """Test evaluating dataset with custom metrics."""
        with patch.object(custom_evaluator, '_evaluate_single') as mock_eval:
            mock_eval.side_effect = [
                {
                    "citation_accuracy": CitationAccuracyResult(score=1.0, citation_coverage=1.0, citation_precision=1.0),
                    "hallucination_rate": HallucinationResult(score=0.0, hallucinated_claims=[], verified_claims=2),
                },
                {
                    "citation_accuracy": CitationAccuracyResult(score=0.9, citation_coverage=0.9, citation_precision=0.95),
                    "hallucination_rate": HallucinationResult(score=0.0, hallucinated_claims=[], verified_claims=2),
                },
            ]

            results = custom_evaluator.evaluate_dataset(sample_dataset)

            assert len(results) == 2

    def test_aggregate_results(self, custom_evaluator):
        """Test aggregating custom evaluation results."""
        results = [
            {
                "citation_accuracy": CitationAccuracyResult(score=1.0, citation_coverage=1.0, citation_precision=1.0),
                "hallucination_rate": HallucinationResult(score=0.0, hallucinated_claims=[], verified_claims=2),
            },
            {
                "citation_accuracy": CitationAccuracyResult(score=0.9, citation_coverage=0.9, citation_precision=0.95),
                "hallucination_rate": HallucinationResult(score=0.05, hallucinated_claims=["minor"], verified_claims=3),
            },
        ]

        aggregated = custom_evaluator.aggregate_results(results)

        assert aggregated["citation_accuracy"] == 0.95
        assert aggregated["hallucination_rate"] == 0.025

    def test_check_thresholds_pass(self, custom_evaluator):
        """Test threshold checking passes."""
        aggregated = {
            "citation_accuracy": 0.96,
            "hallucination_rate": 0.02,
        }

        passed, failures = custom_evaluator.check_thresholds(aggregated)

        assert passed is True
        assert len(failures) == 0

    def test_check_thresholds_fail_citation(self, custom_evaluator):
        """Test threshold checking fails on citation accuracy."""
        aggregated = {
            "citation_accuracy": 0.90,  # Below 0.95
            "hallucination_rate": 0.02,
        }

        passed, failures = custom_evaluator.check_thresholds(aggregated)

        assert passed is False
        assert any("citation_accuracy" in f for f in failures)

    def test_check_thresholds_fail_hallucination(self, custom_evaluator):
        """Test threshold checking fails on hallucination rate."""
        aggregated = {
            "citation_accuracy": 0.96,
            "hallucination_rate": 0.10,  # Above 0.05
        }

        passed, failures = custom_evaluator.check_thresholds(aggregated)

        assert passed is False
        assert any("hallucination_rate" in f for f in failures)


class TestLLMJudgeEvaluator:
    """Test the LLM Judge evaluator for pairwise and absolute scoring."""

    @pytest.fixture
    def judge_config(self):
        return JudgeConfig(
            judge_model="gpt-4o",
            candidate_model="gpt-4o-mini",
            temperature=0.0,
            max_tokens=1000,
        )

    @pytest.fixture
    def sample_pairwise_data(self):
        return [
            {
                "question": "What is the capital of France?",
                "answer_a": "Paris is the capital of France.",
                "answer_b": "The capital of France is Paris, a city in Europe.",
            },
            {
                "question": "Who wrote 1984?",
                "answer_a": "George Orwell wrote 1984.",
                "answer_b": "1984 was written by George Orwell, a British author.",
            }
        ]

    def test_evaluate_pairwise_prefer_a(self, judge_config, sample_pairwise_data):
        """Test pairwise evaluation preferring answer A."""
        evaluator = LLMJudgeEvaluator(judge_config)

        with patch.object(evaluator, '_call_judge_pairwise') as mock_judge:
            mock_judge.return_value = PairwiseResult(
                winner="A",
                score_a=0.8,
                score_b=0.6,
                reasoning="Answer A is more concise and direct",
                confidence=0.9,
            )

            results = evaluator.evaluate_pairwise(sample_pairwise_data)

            assert len(results) == 2
            assert all(r.winner in ["A", "B", "TIE"] for r in results)

    def test_evaluate_pairwise_prefer_b(self, judge_config, sample_pairwise_data):
        """Test pairwise evaluation preferring answer B."""
        evaluator = LLMJudgeEvaluator(judge_config)

        with patch.object(evaluator, '_call_judge_pairwise') as mock_judge:
            mock_judge.return_value = PairwiseResult(
                winner="B",
                score_a=0.6,
                score_b=0.85,
                reasoning="Answer B provides more context",
                confidence=0.85,
            )

            results = evaluator.evaluate_pairwise(sample_pairwise_data)

            assert all(r.winner == "B" for r in results)

    def test_evaluate_pairwise_tie(self, judge_config, sample_pairwise_data):
        """Test pairwise evaluation with tie."""
        evaluator = LLMJudgeEvaluator(judge_config)

        with patch.object(evaluator, '_call_judge_pairwise') as mock_judge:
            mock_judge.return_value = PairwiseResult(
                winner="TIE",
                score_a=0.75,
                score_b=0.75,
                reasoning="Both answers are equally good",
                confidence=0.7,
            )

            results = evaluator.evaluate_pairwise(sample_pairwise_data)

            assert all(r.winner == "TIE" for r in results)

    def test_calculate_win_rate(self, judge_config):
        """Test win rate calculation."""
        evaluator = LLMJudgeEvaluator(judge_config)

        pairwise_results = [
            PairwiseResult(winner="A", score_a=0.8, score_b=0.6, reasoning="", confidence=0.9),
            PairwiseResult(winner="A", score_a=0.7, score_b=0.5, reasoning="", confidence=0.8),
            PairwiseResult(winner="B", score_a=0.5, score_b=0.8, reasoning="", confidence=0.8),
            PairwiseResult(winner="TIE", score_a=0.7, score_b=0.7, reasoning="", confidence=0.7),
            PairwiseResult(winner="A", score_a=0.9, score_b=0.6, reasoning="", confidence=0.95),
        ]

        win_rate = evaluator.calculate_win_rate(pairwise_results)

        # A wins 3, B wins 1, Tie 1 -> A win rate = 3/5 = 0.6
        assert win_rate == 0.6

    def test_evaluate_absolute(self, judge_config):
        """Test absolute scoring evaluation."""
        evaluator = LLMJudgeEvaluator(judge_config)

        test_data = [
            {
                "question": "What is the capital of France?",
                "answer": "Paris is the capital of France.",
                "criteria": "accuracy, completeness, clarity",
            }
        ]

        with patch.object(evaluator, '_call_judge_absolute') as mock_judge:
            mock_judge.return_value = AbsoluteScoreResult(
                score=0.9,
                reasoning="Accurate, complete, and clear",
                criteria_scores={"accuracy": 1.0, "completeness": 0.9, "clarity": 0.8},
            )

            results = evaluator.evaluate_absolute(test_data)

            assert len(results) == 1
            assert results[0].score == 0.9

    def test_check_win_rate_threshold(self, judge_config):
        """Test win rate threshold checking."""
        evaluator = LLMJudgeEvaluator(judge_config)

        # Win rate above threshold
        pairwise_results = [
            PairwiseResult(winner="A", score_a=0.8, score_b=0.6, reasoning="", confidence=0.9),
            PairwiseResult(winner="A", score_a=0.7, score_b=0.5, reasoning="", confidence=0.8),
            PairwiseResult(winner="A", score_a=0.9, score_b=0.6, reasoning="", confidence=0.95),
        ]
        passed, msg = evaluator.check_win_rate_threshold(pairwise_results, threshold=0.60)
        assert passed is True

        # Win rate below threshold
        pairwise_results_low = [
            PairwiseResult(winner="A", score_a=0.8, score_b=0.6, reasoning="", confidence=0.9),
            PairwiseResult(winner="B", score_a=0.5, score_b=0.8, reasoning="", confidence=0.8),
            PairwiseResult(winner="B", score_a=0.4, score_b=0.9, reasoning="", confidence=0.9),
        ]
        passed, msg = evaluator.check_win_rate_threshold(pairwise_results_low, threshold=0.60)
        assert passed is False


# Integration test markers
@pytest.mark.integration
class TestGenerationEvaluationIntegration:
    """Integration tests requiring actual LLM API keys."""

    @pytest.mark.skipif(
        not pytest.config.getoption("--run-integration", default=False),
        reason="Requires --run-integration flag and API keys"
    )
    def test_full_ragas_pipeline(self):
        """Test full RAGAS evaluation pipeline with real API."""
        pass

    @pytest.mark.skipif(
        not pytest.config.getoption("--run-integration", default=False),
        reason="Requires --run-integration flag and API keys"
    )
    def test_full_llm_judge_pipeline(self):
        """Test full LLM Judge evaluation pipeline with real API."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
