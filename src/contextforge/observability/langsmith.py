"""
LangSmith Integration for CI Evaluation Runs

Provides client for running evaluations in CI/CD with LangSmith:
- Dataset management for golden sets
- Experiment runs with comparison
- Evaluation results tracking
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Optional import
try:
    from langsmith import Client as LangSmithClient
    from langsmith.evaluation import evaluate
    from langsmith.schemas import Example, Run
    LANGSCHAIN_AVAILABLE = True
except ImportError:
    LANGSCHAIN_AVAILABLE = False
    LangSmithClient = None
    evaluate = None
    Run = Example = None


class LangSmithConfig(BaseModel):
    """Configuration for LangSmith client."""

    api_key: str = Field(default_factory=lambda: os.getenv("LANGCHAIN_API_KEY", ""))
    project: str = Field(default_factory=lambda: os.getenv("LANGCHAIN_PROJECT", "contextforge"))
    endpoint: str = Field(default_factory=lambda: os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"))
    enabled: bool = Field(default=True)


@dataclass
class ExperimentConfig:
    """Configuration for an evaluation experiment."""

    experiment_name: str
    dataset_name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LangSmithEvaluator:
    """
    LangSmith client for CI evaluation runs.

    Usage:
        evaluator = LangSmithEvaluator(config)
        # Create dataset from golden QA pairs
        dataset = evaluator.create_dataset("golden-qa-v1", qa_pairs)

        # Run evaluation
        results = evaluator.run_evaluation(
            experiment_name="ragas-eval-v1",
            dataset_name="golden-qa-v1",
            target_fn=rag_pipeline,
            evaluators=[faithfulness_evaluator, answer_relevancy_evaluator],
        )
    """

    def __init__(self, config: LangSmithConfig = None):
        self.config = config or LangSmithConfig()
        self._client: LangSmithClient | None = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize LangSmith client."""
        if not LANGSCHAIN_AVAILABLE:
            return

        if not self.config.api_key:
            return

        if not self.config.enabled:
            return

        try:
            self._client = LangSmithClient(
                api_key=self.config.api_key,
                api_url=self.config.endpoint,
            )
        except Exception as e:
            print(f"[LangSmith] Failed to initialize: {e}")

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    def create_dataset(
        self,
        dataset_name: str,
        examples: list[dict[str, Any]],
        description: str = "",
    ) -> str | None:
        """
        Create a dataset from examples.

        Args:
            dataset_name: Name of the dataset
            examples: List of dicts with inputs/outputs
            description: Dataset description

        Returns:
            Dataset ID if successful
        """
        if not self._client:
            return None

        try:
            # Check if dataset exists
            datasets = list(self._client.list_datasets(dataset_name=dataset_name))
            if datasets:
                dataset = datasets[0]
            else:
                dataset = self._client.create_dataset(
                    dataset_name=dataset_name,
                    description=description,
                )

            # Add examples
            for ex in examples:
                self._client.create_example(
                    inputs=ex.get("inputs", {}),
                    outputs=ex.get("outputs", {}),
                    metadata=ex.get("metadata", {}),
                    dataset_id=dataset.id,
                )

            return str(dataset.id)
        except Exception as e:
            print(f"[LangSmith] Failed to create dataset: {e}")
            return None

    def get_dataset(self, dataset_name: str) -> list[Example] | None:
        """Get examples from a dataset."""
        if not self._client:
            return None

        try:
            datasets = list(self._client.list_datasets(dataset_name=dataset_name))
            if not datasets:
                return None

            examples = list(self._client.list_examples(dataset_id=datasets[0].id))
            return examples
        except Exception as e:
            print(f"[LangSmith] Failed to get dataset: {e}")
            return None

    def run_evaluation(
        self,
        experiment_name: str,
        dataset_name: str,
        target_fn: Callable,
        evaluators: list[Callable],
        experiment_config: ExperimentConfig = None,
        max_concurrency: int = 5,
    ) -> dict[str, Any] | None:
        """
        Run evaluation experiment.

        Args:
            experiment_name: Name for this experiment run
            dataset_name: Dataset to evaluate on
            target_fn: Function to evaluate (takes inputs, returns outputs)
            evaluators: List of evaluator functions
            experiment_config: Additional experiment configuration
            max_concurrency: Max concurrent evaluations

        Returns:
            Experiment results
        """
        if not self._client or not evaluate:
            return None

        try:
            dataset = self.get_dataset(dataset_name)
            if not dataset:
                print(f"[LangSmith] Dataset not found: {dataset_name}")
                return None

            # Run evaluation
            results = evaluate(
                target_fn,
                data=dataset,
                evaluators=evaluators,
                experiment_prefix=experiment_name,
                max_concurrency=max_concurrency,
                metadata=experiment_config.metadata if experiment_config else {},
            )

            return {
                "experiment_name": experiment_name,
                "dataset_name": dataset_name,
                "results": results,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"[LangSmith] Evaluation failed: {e}")
            return None

    def list_experiments(self, dataset_name: str = None) -> list[dict[str, Any]]:
        """List experiments, optionally filtered by dataset."""
        if not self._client:
            return []

        try:
            experiments = self._client.list_experiments()
            if dataset_name:
                experiments = [e for e in experiments if e.dataset_name == dataset_name]
            return [
                {
                    "name": e.name,
                    "dataset_name": e.dataset_name,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "status": e.status,
                }
                for e in experiments
            ]
        except Exception as e:
            print(f"[LangSmith] Failed to list experiments: {e}")
            return []

    def compare_experiments(self, experiment_names: list[str]) -> dict[str, Any] | None:
        """Compare multiple experiments."""
        if not self._client:
            return None

        try:
            # Get experiment results
            experiments = []
            for name in experiment_names:
                exps = list(self._client.list_experiments(experiment_name=name))
                if exps:
                    experiments.append(exps[0])

            if len(experiments) < 2:
                return None

            # Compare using LangSmith's comparison
            comparison = self._client.compare_experiments(
                experiment_ids=[str(e.id) for e in experiments]
            )

            return comparison
        except Exception as e:
            print(f"[LangSmith] Comparison failed: {e}")
            return None


# Evaluator functions for common metrics

def create_faithfulness_evaluator():
    """Create faithfulness evaluator for LangSmith."""
    def evaluator(run: Run, example: Example) -> dict[str, Any]:
        # Extract answer and contexts from run
        answer = run.outputs.get("answer", "") if run.outputs else ""
        contexts = run.outputs.get("contexts", []) if run.outputs else []

        # Simple heuristic faithfulness check
        # In production, use LLM-based evaluation
        claims = answer.split(".")
        supported = 0
        for claim in claims:
            claim = claim.strip()
            if not claim:
                continue
            claim_words = set(claim.lower().split())
            for ctx in contexts:
                ctx_words = set(ctx.lower().split())
                if claim_words & ctx_words:
                    supported += 1
                    break

        score = supported / len(claims) if claims else 1.0
        return {"score": score, "key": "faithfulness"}

    return evaluator


def create_answer_relevancy_evaluator():
    """Create answer relevancy evaluator for LangSmith."""
    def evaluator(run: Run, example: Example) -> dict[str, Any]:
        question = example.inputs.get("question", "")
        answer = run.outputs.get("answer", "") if run.outputs else ""

        if not question or not answer:
            return {"score": 0.0, "key": "answer_relevancy"}

        # Keyword overlap heuristic
        q_words = set(question.lower().split())
        a_words = set(answer.lower().split())

        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        q_words -= stop_words
        a_words -= stop_words

        if not q_words:
            return {"score": 1.0, "key": "answer_relevancy"}

        overlap = q_words & a_words
        score = len(overlap) / len(q_words)
        return {"score": min(1.0, score * 1.5), "key": "answer_relevancy"}

    return evaluator


def create_context_precision_evaluator():
    """Create context precision evaluator for LangSmith."""
    def evaluator(run: Run, example: Example) -> dict[str, Any]:
        contexts = run.outputs.get("contexts", []) if run.outputs else []
        relevant_contexts = example.outputs.get("relevant_contexts", [])

        if not contexts or not relevant_contexts:
            return {"score": 0.0, "key": "context_precision"}

        # Average precision
        relevant_set = set(relevant_contexts)
        precision_sum = 0.0
        relevant_found = 0

        for i, ctx in enumerate(contexts, 1):
            if ctx in relevant_set:
                relevant_found += 1
                precision_sum += relevant_found / i

        score = precision_sum / len(relevant_contexts) if relevant_contexts else 0.0
        return {"score": score, "key": "context_precision"}

    return evaluator


def create_context_recall_evaluator():
    """Create context recall evaluator for LangSmith."""
    def evaluator(run: Run, example: Example) -> dict[str, Any]:
        contexts = run.outputs.get("contexts", []) if run.outputs else []
        relevant_contexts = example.outputs.get("relevant_contexts", [])

        if not relevant_contexts:
            return {"score": 1.0, "key": "context_recall"}

        retrieved_set = set(contexts)
        relevant_set = set(relevant_contexts)
        retrieved_relevant = retrieved_set & relevant_set

        score = len(retrieved_relevant) / len(relevant_set)
        return {"score": score, "key": "context_recall"}

    return evaluator


def get_default_evaluators() -> list[Callable]:
    """Get default RAGAS evaluators for LangSmith."""
    return [
        create_faithfulness_evaluator(),
        create_answer_relevancy_evaluator(),
        create_context_precision_evaluator(),
        create_context_recall_evaluator(),
    ]


def create_langsmith_evaluator(
    api_key: str = None,
    project: str = None,
    enabled: bool = True,
) -> LangSmithEvaluator:
    """Create LangSmith evaluator with custom config."""
    config = LangSmithConfig(
        api_key=api_key or os.getenv("LANGCHAIN_API_KEY", ""),
        project=project or os.getenv("LANGCHAIN_PROJECT", "contextforge"),
        enabled=enabled,
    )
    return LangSmithEvaluator(config)


class LangSmithEvaluator:
    """
    LangSmith client for CI evaluation runs.

    Usage:
        evaluator = LangSmithEvaluator(config)
        # Create dataset from golden QA pairs
        dataset = evaluator.create_dataset("golden-qa-v1", qa_pairs)

        # Run evaluation
        results = evaluator.run_evaluation(
            experiment_name="ragas-eval-v1",
            dataset_name="golden-qa-v1",
            target_fn=rag_pipeline,
            evaluators=[faithfulness_evaluator, answer_relevancy_evaluator],
        )
    """

    def __init__(self, config: LangSmithConfig = None):
        self.config = config or LangSmithConfig()
        self._client: LangSmithClient | None = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize LangSmith client."""
        if not LANGSCHAIN_AVAILABLE:
            return

        if not self.config.api_key:
            return

        if not self.config.enabled:
            return

        try:
            self._client = LangSmithClient(
                api_key=self.config.api_key,
                api_url=self.config.endpoint,
            )
        except Exception as e:
            print(f"[LangSmith] Failed to initialize: {e}")

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    def create_dataset(
        self,
        dataset_name: str,
        examples: list[dict[str, Any]],
        description: str = "",
    ) -> str | None:
        """
        Create a dataset from examples.

        Args:
            dataset_name: Name of the dataset
            examples: List of dicts with inputs/outputs
            description: Dataset description

        Returns:
            Dataset ID if successful
        """
        if not self._client:
            return None

        try:
            # Check if dataset exists
            datasets = list(self._client.list_datasets(dataset_name=dataset_name))
            if datasets:
                dataset = datasets[0]
            else:
                dataset = self._client.create_dataset(
                    dataset_name=dataset_name,
                    description=description,
                )

            # Add examples
            for ex in examples:
                self._client.create_example(
                    inputs=ex.get("inputs", {}),
                    outputs=ex.get("outputs", {}),
                    metadata=ex.get("metadata", {}),
                    dataset_id=dataset.id,
                )

            return str(dataset.id)
        except Exception as e:
            print(f"[LangSmith] Failed to create dataset: {e}")
            return None

    def push_golden_set(self, golden_set_path: str, dataset_name: str) -> str | None:
        """
        Push golden set JSONL file to LangSmith as a dataset.

        Args:
            golden_set_path: Path to golden set JSONL file
            dataset_name: Name for the dataset in LangSmith

        Returns:
            Dataset ID if successful
        """
        if not self._client:
            print("[LangSmith] Client not initialized, skipping push")
            return None

        import json
        from pathlib import Path

        path = Path(golden_set_path)
        if not path.exists():
            print(f"[LangSmith] Golden set not found: {golden_set_path}")
            return None

        examples = []
        with open(path) as f:
            for line in f:
                item = json.loads(line)
                # Convert QA pair to LangSmith example format
                examples.append({
                    "inputs": {"question": item.get("question", "")},
                    "outputs": {"answer": item.get("answer", "")},
                    "metadata": item.get("metadata", {}),
                })

        description = f"Golden QA pairs from {path.name} ({len(examples)} examples)"
        return self.create_dataset(dataset_name, examples, description)

    def get_dataset(self, dataset_name: str) -> list[Example] | None:
        """Get examples from a dataset."""
        if not self._client:
            return None

        try:
            datasets = list(self._client.list_datasets(dataset_name=dataset_name))
            if not datasets:
                return None

            examples = list(self._client.list_examples(dataset_id=datasets[0].id))
            return examples
        except Exception as e:
            print(f"[LangSmith] Failed to get dataset: {e}")
            return None

    def run_evaluation(
        self,
        experiment_name: str,
        dataset_name: str,
        target_fn: Callable,
        evaluators: list[Callable],
        experiment_config: ExperimentConfig = None,
        max_concurrency: int = 5,
    ) -> dict[str, Any] | None:
        """
        Run evaluation experiment.

        Args:
            experiment_name: Name for this experiment run
            dataset_name: Dataset to evaluate on
            target_fn: Function to evaluate (takes inputs, returns outputs)
            evaluators: List of evaluator functions
            experiment_config: Additional experiment configuration
            max_concurrency: Max concurrent evaluations

        Returns:
            Experiment results
        """
        if not self._client or not evaluate:
            return None

        try:
            dataset = self.get_dataset(dataset_name)
            if not dataset:
                print(f"[LangSmith] Dataset not found: {dataset_name}")
                return None

            # Run evaluation
            results = evaluate(
                target_fn,
                data=dataset,
                evaluators=evaluators,
                experiment_prefix=experiment_name,
                max_concurrency=max_concurrency,
                metadata=experiment_config.metadata if experiment_config else {},
            )

            return {
                "experiment_name": experiment_name,
                "dataset_name": dataset_name,
                "results": results,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"[LangSmith] Evaluation failed: {e}")
            return None

    def list_experiments(self, dataset_name: str = None) -> list[dict[str, Any]]:
        """List experiments, optionally filtered by dataset."""
        if not self._client:
            return []

        try:
            experiments = self._client.list_experiments()
            if dataset_name:
                experiments = [e for e in experiments if e.dataset_name == dataset_name]
            return [
                {
                    "name": e.name,
                    "dataset_name": e.dataset_name,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "status": e.status,
                }
                for e in experiments
            ]
        except Exception as e:
            print(f"[LangSmith] Failed to list experiments: {e}")
            return []

    def compare_experiments(self, experiment_names: list[str]) -> dict[str, Any] | None:
        """Compare multiple experiments."""
        if not self._client:
            return None

        try:
            # Get experiment results
            experiments = []
            for name in experiment_names:
                exps = list(self._client.list_experiments(experiment_name=name))
                if exps:
                    experiments.append(exps[0])

            if len(experiments) < 2:
                return None

            # Compare using LangSmith's comparison
            comparison = self._client.compare_experiments(
                experiment_ids=[str(e.id) for e in experiments]
            )

            return comparison
        except Exception as e:
            print(f"[LangSmith] Comparison failed: {e}")
            return None
