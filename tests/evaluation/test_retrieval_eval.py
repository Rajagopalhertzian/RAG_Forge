"""
Tests for Retrieval Evaluation Pipeline

Tests cover:
- Metrics computation (MRR, NDCG, Recall, Precision, Latency)
- Golden dataset loading and validation
- Evaluation runner with threshold checking
- CI integration and gating
"""

import json
import tempfile
from unittest.mock import Mock, patch

import pytest

from contextforge.evaluation.retrieval.dataset import (
    GoldenQA,
    GoldenQADataset,
    load_golden_dataset,
    validate_golden_dataset,
)
from contextforge.evaluation.retrieval.metrics import (
    RetrievalMetrics,
    RetrievalMetricsCalculator,
    compute_mrr_at_k,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
)
from contextforge.evaluation.retrieval.runner import (
    EvaluationConfig,
    EvaluationResult,
    RetrievalEvaluator,
    run_retrieval_evaluation,
)
from contextforge.evaluation.retrieval.thresholds import (
    RetrievalThresholds,
    ThresholdCheckResult,
    ThresholdGate,
    load_thresholds_from_yaml,
)


class TestRetrievalMetrics:
    """Test core IR metrics computations."""

    def test_mrr_at_k_perfect_match(self):
        """Test MRR@k with perfect first result."""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = ["doc1"]
        assert compute_mrr_at_k(retrieved, relevant, k=10) == 1.0

    def test_mrr_at_k_second_position(self):
        """Test MRR@k with relevant at second position."""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = ["doc2"]
        assert compute_mrr_at_k(retrieved, relevant, k=10) == 0.5

    def test_mrr_at_k_not_in_top_k(self):
        """Test MRR@k when relevant not in top-k."""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = ["doc4"]
        assert compute_mrr_at_k(retrieved, relevant, k=3) == 0.0

    def test_mrr_at_k_multiple_relevant(self):
        """Test MRR@k with multiple relevant docs."""
        retrieved = ["doc1", "doc2", "doc3", "doc4"]
        relevant = ["doc2", "doc4"]
        # First relevant at position 2 (1-indexed)
        assert compute_mrr_at_k(retrieved, relevant, k=10) == 0.5

    def test_mrr_at_k_empty_retrieved(self):
        """Test MRR@k with empty retrieved list."""
        retrieved = []
        relevant = ["doc1"]
        assert compute_mrr_at_k(retrieved, relevant, k=10) == 0.0

    def test_mrr_at_k_empty_relevant(self):
        """Test MRR@k with empty relevant list."""
        retrieved = ["doc1", "doc2"]
        relevant = []
        assert compute_mrr_at_k(retrieved, relevant, k=10) == 0.0

    def test_ndcg_at_k_perfect_ranking(self):
        """Test NDCG@k with perfect ranking."""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = ["doc1", "doc2", "doc3"]
        assert compute_ndcg_at_k(retrieved, relevant, k=10) == 1.0

    def test_ndcg_at_k_reversed_ranking(self):
        """Test NDCG@k with reversed ranking."""
        retrieved = ["doc3", "doc2", "doc1"]
        relevant = ["doc1", "doc2", "doc3"]
        # Should be less than 1.0
        ndcg = compute_ndcg_at_k(retrieved, relevant, k=10)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_at_k_partial_relevant(self):
        """Test NDCG@k with only some relevant in top-k."""
        retrieved = ["doc1", "doc4", "doc2"]
        relevant = ["doc1", "doc2", "doc3"]
        ndcg = compute_ndcg_at_k(retrieved, relevant, k=3)
        assert 0.0 < ndcg < 1.0

    def test_recall_at_k_all_retrieved(self):
        """Test Recall@k when all relevant retrieved."""
        retrieved = ["doc1", "doc2", "doc3", "doc4"]
        relevant = ["doc1", "doc2"]
        assert compute_recall_at_k(retrieved, relevant, k=10) == 1.0

    def test_recall_at_k_partial(self):
        """Test Recall@k with partial retrieval."""
        retrieved = ["doc1", "doc3", "doc4"]
        relevant = ["doc1", "doc2", "doc3"]
        # 2 out of 3 relevant retrieved
        assert compute_recall_at_k(retrieved, relevant, k=10) == 2/3

    def test_recall_at_k_none_retrieved(self):
        """Test Recall@k when none relevant retrieved."""
        retrieved = ["doc4", "doc5"]
        relevant = ["doc1", "doc2"]
        assert compute_recall_at_k(retrieved, relevant, k=10) == 0.0

    def test_recall_at_k_empty_relevant(self):
        """Test Recall@k with empty relevant set."""
        retrieved = ["doc1", "doc2"]
        relevant = []
        assert compute_recall_at_k(retrieved, relevant, k=10) == 1.0

    def test_precision_at_k_all_relevant(self):
        """Test Precision@k when all retrieved are relevant."""
        retrieved = ["doc1", "doc2"]
        relevant = ["doc1", "doc2", "doc3"]
        assert compute_precision_at_k(retrieved, relevant, k=10) == 1.0

    def test_precision_at_k_partial(self):
        """Test Precision@k with partial relevance."""
        retrieved = ["doc1", "doc4", "doc5"]
        relevant = ["doc1", "doc2", "doc3"]
        # 1 out of 3 retrieved are relevant
        assert compute_precision_at_k(retrieved, relevant, k=10) == 1/3

    def test_precision_at_k_none_relevant(self):
        """Test Precision@k when none retrieved are relevant."""
        retrieved = ["doc4", "doc5"]
        relevant = ["doc1", "doc2"]
        assert compute_precision_at_k(retrieved, relevant, k=10) == 0.0


class TestRetrievalMetricsCalculator:
    """Test the RetrievalMetricsCalculator class."""

    @pytest.fixture
    def calculator(self):
        return RetrievalMetricsCalculator(k_values=[5, 10, 20])

    @pytest.fixture
    def sample_results(self):
        return [
            {
                "query_id": "q1",
                "retrieved_docs": ["doc1", "doc2", "doc3", "doc4", "doc5"],
                "relevant_docs": ["doc1", "doc3"],
                "latency_ms": 150.0,
            },
            {
                "query_id": "q2",
                "retrieved_docs": ["doc6", "doc7", "doc8"],
                "relevant_docs": ["doc7"],
                "latency_ms": 200.0,
            },
            {
                "query_id": "q3",
                "retrieved_docs": ["doc9", "doc10"],
                "relevant_docs": ["doc11", "doc12"],
                "latency_ms": 180.0,
            },
        ]

    def test_calculate_metrics(self, calculator, sample_results):
        metrics = calculator.calculate(sample_results)

        assert isinstance(metrics, RetrievalMetrics)
        assert metrics.mrr_at_10 > 0
        assert metrics.recall_at_10 >= 0
        assert metrics.precision_at_10 >= 0
        assert metrics.ndcg_at_10 >= 0
        assert metrics.latency_p50_ms > 0
        assert metrics.latency_p95_ms > 0
        assert metrics.latency_mean_ms > 0
        assert metrics.num_queries == 3

    def test_calculate_empty_results(self, calculator):
        metrics = calculator.calculate([])

        assert metrics.num_queries == 0
        assert metrics.mrr_at_10 == 0.0
        assert metrics.recall_at_10 == 0.0

    def test_percentile_calculation(self, calculator):
        latencies = [100, 200, 300, 400, 500]
        p50 = calculator._percentile(latencies, 50)
        p95 = calculator._percentile(latencies, 95)

        assert p50 == 300
        assert p95 == 500


class TestGoldenQADataset:
    """Test Golden QA Dataset loading and validation."""

    @pytest.fixture
    def sample_jsonl(self):
        data = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "question": "What is the capital of France?",
                "answer": "The capital of France is Paris.",
                "relevant_docs": ["doc_001", "doc_002"],
                "metadata": {
                    "version": "v1",
                    "created_at": "2024-01-15T10:00:00Z",
                    "category": "geography",
                    "difficulty": "easy",
                    "tags": ["capital", "france"],
                    "source": "wikipedia"
                }
            },
            {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "question": "Who wrote 1984?",
                "answer": "George Orwell wrote 1984.",
                "relevant_docs": ["doc_003"],
                "metadata": {
                    "version": "v1",
                    "created_at": "2024-01-15T10:00:00Z",
                    "category": "literature",
                    "difficulty": "easy",
                    "tags": ["author", "george orwell"],
                    "source": "wikipedia"
                }
            }
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
            return f.name

    def test_load_golden_dataset(self, sample_jsonl):
        dataset = load_golden_dataset(sample_jsonl)

        assert isinstance(dataset, GoldenQADataset)
        assert len(dataset.questions) == 2
        assert dataset.questions[0].id == "550e8400-e29b-41d4-a716-446655440001"
        assert dataset.questions[0].question == "What is the capital of France?"
        assert dataset.questions[0].relevant_docs == ["doc_001", "doc_002"]

    def test_load_golden_dataset_invalid_path(self):
        with pytest.raises(FileNotFoundError):
            load_golden_dataset("/nonexistent/path.jsonl")

    def test_validate_golden_dataset_valid(self, sample_jsonl):
        dataset = load_golden_dataset(sample_jsonl)
        errors = validate_golden_dataset(dataset)

        assert len(errors) == 0

    def test_validate_golden_dataset_missing_fields(self):
        # Create invalid dataset
        data = [{
            "id": "test",
            "question": "Test?",
            # Missing answer, relevant_docs, metadata
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
            path = f.name

        dataset = load_golden_dataset(path)
        errors = validate_golden_dataset(dataset)

        assert len(errors) > 0
        assert any("answer" in e for e in errors)
        assert any("relevant_docs" in e for e in errors)

    def test_validate_golden_dataset_duplicate_ids(self):
        data = [
            {"id": "dup", "question": "Q1?", "answer": "A1", "relevant_docs": ["d1"], "metadata": {"version": "v1", "created_at": "2024-01-01", "category": "test", "difficulty": "easy", "tags": [], "source": "test"}},
            {"id": "dup", "question": "Q2?", "answer": "A2", "relevant_docs": ["d2"], "metadata": {"version": "v1", "created_at": "2024-01-01", "category": "test", "difficulty": "easy", "tags": [], "source": "test"}},
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
            path = f.name

        dataset = load_golden_dataset(path)
        errors = validate_golden_dataset(dataset)

        assert any("duplicate" in e.lower() for e in errors)

    def test_golden_qa_dataclass(self):
        qa = GoldenQA(
            id="test-1",
            question="Test question?",
            answer="Test answer",
            relevant_docs=["doc1"],
            metadata={"version": "v1", "category": "test"}
        )

        assert qa.id == "test-1"
        assert qa.question == "Test question?"


class TestRetrievalEvaluator:
    """Test the RetrievalEvaluator class."""

    @pytest.fixture
    def mock_retriever(self):
        retriever = Mock()
        retriever.retrieve.return_value = [
            {"doc_id": "doc1", "score": 0.9},
            {"doc_id": "doc2", "score": 0.8},
            {"doc_id": "doc3", "score": 0.7},
        ]
        return retriever

    @pytest.fixture
    def sample_dataset(self):
        qa1 = GoldenQA(
            id="q1",
            question="What is Paris?",
            answer="Capital of France",
            relevant_docs=["doc1", "doc2"],
            metadata={"version": "v1", "category": "geo"}
        )
        qa2 = GoldenQA(
            id="q2",
            question="What is London?",
            answer="Capital of UK",
            relevant_docs=["doc3"],
            metadata={"version": "v1", "category": "geo"}
        )
        return GoldenQADataset(questions=[qa1, qa2], version="v1")

    @pytest.fixture
    def evaluator(self, mock_retriever, sample_dataset):
        config = EvaluationConfig(
            k_values=[5, 10],
            timeout_seconds=30,
        )
        return RetrievalEvaluator(
            retriever=mock_retriever,
            dataset=sample_dataset,
            config=config,
        )

    def test_evaluate(self, evaluator, mock_retriever):
        result = evaluator.evaluate()

        assert isinstance(result, EvaluationResult)
        assert result.num_queries == 2
        assert result.metrics is not None
        assert result.metrics.num_queries == 2
        # Verify retriever was called for each query
        assert mock_retriever.retrieve.call_count == 2

    def test_evaluate_with_latency(self, evaluator, mock_retriever):
        import time
        # Add latency to mock
        def slow_retrieve(query, k=10):
            time.sleep(0.01)
            return [{"doc_id": "doc1", "score": 0.9}]

        mock_retriever.retrieve.side_effect = slow_retrieve

        result = evaluator.evaluate()

        assert result.metrics.latency_mean_ms > 0
        assert result.metrics.latency_p50_ms > 0

    def test_evaluate_empty_dataset(self, mock_retriever):
        empty_dataset = GoldenQADataset(questions=[], version="v1")
        config = EvaluationConfig(k_values=[10])
        evaluator = RetrievalEvaluator(
            retriever=mock_retriever,
            dataset=empty_dataset,
            config=config,
        )

        result = evaluator.evaluate()

        assert result.num_queries == 0
        assert result.metrics.num_queries == 0


class TestThresholdGate:
    """Test threshold checking and gating logic."""

    @pytest.fixture
    def thresholds(self):
        return RetrievalThresholds(
            mrr_at_10=0.65,
            recall_at_10=0.70,
            ndcg_at_10=0.60,
            precision_at_10=0.30,
            latency_p95_ms=800,
        )

    @pytest.fixture
    def passing_metrics(self):
        return RetrievalMetrics(
            mrr_at_10=0.70,
            recall_at_10=0.75,
            ndcg_at_10=0.65,
            precision_at_10=0.35,
            latency_p50_ms=200,
            latency_p95_ms=500,
            latency_mean_ms=250,
            num_queries=100,
        )

    @pytest.fixture
    def failing_metrics(self):
        return RetrievalMetrics(
            mrr_at_10=0.50,  # Below threshold
            recall_at_10=0.75,
            ndcg_at_10=0.65,
            precision_at_10=0.35,
            latency_p50_ms=200,
            latency_p95_ms=1000,  # Above threshold
            latency_mean_ms=250,
            num_queries=100,
        )

    def test_threshold_check_pass(self, thresholds, passing_metrics):
        gate = ThresholdGate(thresholds)
        result = gate.check(passing_metrics)

        assert isinstance(result, ThresholdCheckResult)
        assert result.passed is True
        assert len(result.failures) == 0

    def test_threshold_check_fail_mrr(self, thresholds, failing_metrics):
        gate = ThresholdGate(thresholds)
        result = gate.check(failing_metrics)

        assert result.passed is False
        assert any("mrr_at_10" in f for f in result.failures)
        assert any("latency_p95_ms" in f for f in result.failures)

    def test_threshold_check_multiple_failures(self, thresholds):
        bad_metrics = RetrievalMetrics(
            mrr_at_10=0.40,
            recall_at_10=0.40,
            ndcg_at_10=0.30,
            precision_at_10=0.10,
            latency_p50_ms=500,
            latency_p95_ms=2000,
            latency_mean_ms=600,
            num_queries=100,
        )
        gate = ThresholdGate(thresholds)
        result = gate.check(bad_metrics)

        assert result.passed is False
        assert len(result.failures) >= 4

    def test_load_thresholds_from_yaml(self):
        yaml_content = """
        mrr_at_10: 0.65
        recall_at_10: 0.70
        ndcg_at_10: 0.60
        precision_at_10: 0.30
        latency_p95_ms: 800
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            path = f.name

        thresholds = load_thresholds_from_yaml(path)

        assert thresholds.mrr_at_10 == 0.65
        assert thresholds.latency_p95_ms == 800


class TestRunRetrievalEvaluation:
    """Test the main entry point for retrieval evaluation."""

    @patch('contextforge.evaluation.retrieval.runner.RetrievalEvaluator')
    def test_run_retrieval_evaluation_success(self, mock_evaluator_class):
        # Setup mock
        mock_evaluator = Mock()
        mock_result = EvaluationResult(
            num_queries=10,
            metrics=RetrievalMetrics(
                mrr_at_10=0.70,
                recall_at_10=0.75,
                ndcg_at_10=0.65,
                precision_at_10=0.35,
                latency_p50_ms=200,
                latency_p95_ms=500,
                latency_mean_ms=250,
                num_queries=10,
            ),
            threshold_check=ThresholdCheckResult(passed=True, failures=[]),
            details=[],
        )
        mock_evaluator.evaluate.return_value = mock_result
        mock_evaluator_class.return_value = mock_evaluator

        # Run
        result = run_retrieval_evaluation(
            dataset_path="tests/evaluation/golden_sets/v1_baseline.jsonl",
            retriever=Mock(),
            output_dir="test_output",
            thresholds_path="contextforge/evaluation/retrieval/thresholds.yaml",
            fail_on_threshold=True,
        )

        assert result.threshold_check.passed is True

    @patch('contextforge.evaluation.retrieval.runner.RetrievalEvaluator')
    def test_run_retrieval_evaluation_fail_on_threshold(self, mock_evaluator_class):
        # Setup mock with failing thresholds
        mock_evaluator = Mock()
        mock_result = EvaluationResult(
            num_queries=10,
            metrics=RetrievalMetrics(
                mrr_at_10=0.50,
                recall_at_10=0.75,
                ndcg_at_10=0.65,
                precision_at_10=0.35,
                latency_p50_ms=200,
                latency_p95_ms=500,
                latency_mean_ms=250,
                num_queries=10,
            ),
            threshold_check=ThresholdCheckResult(
                passed=False,
                failures=["mrr_at_10: 0.50 < 0.65"]
            ),
            details=[],
        )
        mock_evaluator.evaluate.return_value = mock_result
        mock_evaluator_class.return_value = mock_evaluator

        # Should raise when fail_on_threshold=True
        with pytest.raises(SystemExit) as exc_info:
            run_retrieval_evaluation(
                dataset_path="tests/evaluation/golden_sets/v1_baseline.jsonl",
                retriever=Mock(),
                output_dir="test_output",
                thresholds_path="contextforge/evaluation/retrieval/thresholds.yaml",
                fail_on_threshold=True,
            )

        assert exc_info.value.code == 1


# Integration test markers
@pytest.mark.integration
class TestRetrievalEvaluationIntegration:
    """Integration tests requiring actual retriever and API keys."""

    @pytest.mark.skipif(
        not pytest.config.getoption("--run-integration", default=False),
        reason="Requires --run-integration flag and API keys"
    )
    def test_full_retrieval_pipeline(self):
        """Test full retrieval evaluation pipeline with real components."""
        # This would be run manually with real API keys
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
