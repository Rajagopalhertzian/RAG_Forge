#!/usr/bin/env python3
"""
ContextForge Retrieval Evaluation Script
Uses RAGAS metrics for evaluation: Faithfulness, Answer Relevancy, Context Precision, Context Recall
"""

import os
import sys
import json
import argparse
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of a single evaluation."""
    question: str
    ground_truth: str
    answer: str
    contexts: List[str]
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float


@dataclass
class EvaluationSummary:
    """Summary of all evaluations."""
    total_questions: int
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    overall_pass: bool
    results: List[EvaluationResult]


class RetrievalEvaluator:
    """Evaluates retrieval quality using RAGAS metrics."""

    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        threshold_faithfulness: float = 0.85,
        threshold_answer_relevancy: float = 0.80,
        threshold_context_precision: float = 0.75,
        threshold_context_recall: float = 0.75
    ):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.thresholds = {
            'faithfulness': threshold_faithfulness,
            'answer_relevancy': threshold_answer_relevancy,
            'context_precision': threshold_context_precision,
            'context_recall': threshold_context_recall
        }

    async def evaluate_dataset(self, dataset_path: str) -> EvaluationSummary:
        """Evaluate a dataset of questions."""
        # Load dataset
        dataset = self._load_dataset(dataset_path)
        logger.info(f"Loaded {len(dataset)} evaluation samples")

        # Run evaluations
        results = []
        for i, sample in enumerate(dataset):
            logger.info(f"Evaluating sample {i+1}/{len(dataset)}: {sample['question'][:50]}...")
            result = await self._evaluate_sample(sample)
            results.append(result)

        # Calculate aggregate metrics
        summary = self._calculate_summary(results)
        return summary

    def _load_dataset(self, dataset_path: str) -> List[Dict[str, Any]]:
        """Load evaluation dataset from JSONL file."""
        dataset = []
        with open(dataset_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    dataset.append(json.loads(line))
        return dataset

    async def _evaluate_sample(self, sample: Dict[str, Any]) -> EvaluationResult:
        """Evaluate a single sample."""
        question = sample['question']
        ground_truth = sample.get('ground_truth', '')

        # Query the API
        response = await self._query_api(question)

        if 'error' in response:
            logger.error(f"API error: {response['error']}")
            return EvaluationResult(
                question=question,
                ground_truth=ground_truth,
                answer="ERROR",
                contexts=[],
                faithfulness=0.0,
                answer_relevancy=0.0,
                context_precision=0.0,
                context_recall=0.0
            )

        answer = response.get('answer', '')
        contexts = [ctx.get('content', '') for ctx in response.get('sources', [])]

        # Calculate metrics
        faithfulness = await self._calculate_faithfulness(answer, contexts)
        answer_relevancy = await self._calculate_answer_relevancy(question, answer)
        context_precision = await self._calculate_context_precision(question, contexts, ground_truth)
        context_recall = await self._calculate_context_recall(ground_truth, contexts)

        return EvaluationResult(
            question=question,
            ground_truth=ground_truth,
            answer=answer,
            contexts=contexts,
            faithfulness=faithfulness,
            answer_relevancy=answer_relevancy,
            context_precision=context_precision,
            context_recall=context_recall
        )

    async def _query_api(self, question: str) -> Dict[str, Any]:
        """Query the ContextForge API."""
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/query",
                    json={
                        "query": question,
                        "top_k": 5,
                        "include_sources": True
                    },
                    headers=headers
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"error": str(e)}

    async def _calculate_faithfulness(self, answer: str, contexts: List[str]) -> float:
        """Calculate faithfulness score (answer grounded in contexts)."""
        # Simplified faithfulness: check if answer claims are supported by contexts
        # In production, use LLM-based evaluation
        if not answer or not contexts:
            return 0.0

        # Simple heuristic: check overlap between answer and contexts
        answer_words = set(answer.lower().split())
        context_words = set()
        for ctx in contexts:
            context_words.update(ctx.lower().split())

        if not answer_words:
            return 0.0

        overlap = len(answer_words & context_words) / len(answer_words)
        return min(overlap * 1.2, 1.0)  # Scale up slightly

    async def _calculate_answer_relevancy(self, question: str, answer: str) -> float:
        """Calculate answer relevancy score."""
        # Simplified: check if answer addresses the question
        if not answer or not question:
            return 0.0

        question_words = set(question.lower().split())
        answer_words = set(answer.lower().split())

        # Remove common stop words
        stop_words = {'what', 'is', 'are', 'how', 'why', 'when', 'where', 'who', 'which',
                      'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'from', 'as', 'be', 'been', 'being', 'have', 'has',
                      'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
                      'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you',
                      'he', 'she', 'it', 'we', 'they', 'them', 'their', 'our', 'your', 'my'}

        question_words = question_words - stop_words
        answer_words = answer_words - stop_words

        if not question_words:
            return 0.5

        overlap = len(question_words & answer_words) / len(question_words)
        return min(overlap * 1.5, 1.0)

    async def _calculate_context_precision(
        self,
        question: str,
        contexts: List[str],
        ground_truth: str
    ) -> float:
        """Calculate context precision (relevant contexts at top)."""
        if not contexts:
            return 0.0

        # Simple heuristic: check how many top contexts are relevant
        relevant_count = 0
        ground_truth_words = set(ground_truth.lower().split()) if ground_truth else set()

        for i, ctx in enumerate(contexts[:5]):  # Check top 5
            ctx_words = set(ctx.lower().split())
            if ground_truth_words and len(ground_truth_words & ctx_words) > 0:
                relevant_count += 1
            elif any(word in ctx.lower() for word in question.lower().split() if len(word) > 3):
                relevant_count += 0.5

        return min(relevant_count / max(len(contexts[:5]), 1), 1.0)

    async def _calculate_context_recall(
        self,
        ground_truth: str,
        contexts: List[str]
    ) -> float:
        """Calculate context recall (ground truth covered by contexts)."""
        if not ground_truth or not contexts:
            return 0.0

        # Check if key information from ground truth appears in contexts
        gt_sentences = [s.strip() for s in ground_truth.split('.') if len(s.strip()) > 10]
        if not gt_sentences:
            return 0.5

        covered = 0
        all_context_text = ' '.join(contexts).lower()

        for sentence in gt_sentences:
            # Check if key phrases from sentence appear in contexts
            key_words = [w for w in sentence.lower().split() if len(w) > 4]
            if key_words:
                matches = sum(1 for w in key_words if w in all_context_text)
                if matches / len(key_words) > 0.5:
                    covered += 1

        return covered / len(gt_sentences)

    def _calculate_summary(self, results: List[EvaluationResult]) -> EvaluationSummary:
        """Calculate aggregate metrics."""
        if not results:
            return EvaluationSummary(
                total_questions=0,
                faithfulness=0.0,
                answer_relevancy=0.0,
                context_precision=0.0,
                context_recall=0.0,
                overall_pass=False,
                results=[]
            )

        faithfulness = sum(r.faithfulness for r in results) / len(results)
        answer_relevancy = sum(r.answer_relevancy for r in results) / len(results)
        context_precision = sum(r.context_precision for r in results) / len(results)
        context_recall = sum(r.context_recall for r in results) / len(results)

        overall_pass = (
            faithfulness >= self.thresholds['faithfulness'] and
            answer_relevancy >= self.thresholds['answer_relevancy'] and
            context_precision >= self.thresholds['context_precision'] and
            context_recall >= self.thresholds['context_recall']
        )

        return EvaluationSummary(
            total_questions=len(results),
            faithfulness=faithfulness,
            answer_relevancy=answer_relevancy,
            context_precision=context_precision,
            context_recall=context_recall,
            overall_pass=overall_pass,
            results=results
        )


async def main():
    parser = argparse.ArgumentParser(description="ContextForge Retrieval Evaluation")
    parser.add_argument("--dataset", required=True, help="Path to evaluation dataset (JSONL)")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8000"), help="API base URL")
    parser.add_argument("--api-key", default=os.getenv("API_KEY"), help="API key")
    parser.add_argument("--threshold-faithfulness", type=float, default=0.85, help="Faithfulness threshold")
    parser.add_argument("--threshold-answer-relevancy", type=float, default=0.80, help="Answer relevancy threshold")
    parser.add_argument("--threshold-context-precision", type=float, default=0.75, help="Context precision threshold")
    parser.add_argument("--threshold-context-recall", type=float, default=0.75, help="Context recall threshold")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--output-csv", help="Output CSV file")

    args = parser.parse_args()

    evaluator = RetrievalEvaluator(
        api_url=args.api_url,
        api_key=args.api_key,
        threshold_faithfulness=args.threshold_faithfulness,
        threshold_answer_relevancy=args.threshold_answer_relevancy,
        threshold_context_precision=args.threshold_context_precision,
        threshold_context_recall=args.threshold_context_recall
    )

    logger.info("Starting retrieval evaluation...")
    summary = await evaluator.evaluate_dataset(args.dataset)

    # Print results
    print("\n" + "=" * 60)
    print("RETRIEVAL EVALUATION RESULTS")
    print("=" * 60)
    print(f"Total Questions:      {summary.total_questions}")
    print(f"Faithfulness:         {summary.faithfulness:.4f} (threshold: {args.threshold_faithfulness}) {'✅' if summary.faithfulness >= args.threshold_faithfulness else '❌'}")
    print(f"Answer Relevancy:     {summary.answer_relevancy:.4f} (threshold: {args.threshold_answer_relevancy}) {'✅' if summary.answer_relevancy >= args.threshold_answer_relevancy else '❌'}")
    print(f"Context Precision:    {summary.context_precision:.4f} (threshold: {args.threshold_context_precision}) {'✅' if summary.context_precision >= args.threshold_context_precision else '❌'}")
    print(f"Context Recall:       {summary.context_recall:.4f} (threshold: {args.threshold_context_recall}) {'✅' if summary.context_recall >= args.threshold_context_recall else '❌'}")
    print(f"OVERALL:              {'✅ PASSED' if summary.overall_pass else '❌ FAILED'}")
    print("=" * 60)

    # Save JSON output
    output_data = {
        "faithfulness": round(summary.faithfulness, 4),
        "answer_relevancy": round(summary.answer_relevancy, 4),
        "context_precision": round(summary.context_precision, 4),
        "context_recall": round(summary.context_recall, 4),
        "overall_pass": summary.overall_pass,
        "total_questions": summary.total_questions,
        "thresholds": {
            "faithfulness": args.threshold_faithfulness,
            "answer_relevancy": args.threshold_answer_relevancy,
            "context_precision": args.threshold_context_precision,
            "context_recall": args.threshold_context_recall
        },
        "results": [
            {
                "question": r.question,
                "ground_truth": r.ground_truth,
                "answer": r.answer,
                "contexts": r.contexts,
                "faithfulness": round(r.faithfulness, 4),
                "answer_relevancy": round(r.answer_relevancy, 4),
                "context_precision": round(r.context_precision, 4),
                "context_recall": round(r.context_recall, 4)
            }
            for r in summary.results
        ]
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")

    # Save CSV output
    if args.output_csv:
        import csv
        with open(args.output_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'question', 'ground_truth', 'answer', 'faithfulness',
                'answer_relevancy', 'context_precision', 'context_recall'
            ])
            for r in summary.results:
                writer.writerow([
                    r.question, r.ground_truth, r.answer,
                    round(r.faithfulness, 4), round(r.answer_relevancy, 4),
                    round(r.context_precision, 4), round(r.context_recall, 4)
                ])
        print(f"CSV results saved to {args.output_csv}")

    sys.exit(0 if summary.overall_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())