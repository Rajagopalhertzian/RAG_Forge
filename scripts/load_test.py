#!/usr/bin/env python3
"""
ContextForge Load Test Script
Uses Locust for distributed load testing with 1000 QPS target.
"""

import os
import sys
import time
import json
import random
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass
from locust import HttpUser, task, between, events
from locust.env import Environment
from locust.log import setup_logging
from locust.stats import stats_printer, stats_history
import gevent


@dataclass
class LoadTestConfig:
    """Configuration for load test."""
    host: str
    users: int
    spawn_rate: int
    run_time: str
    target_qps: int
    api_key: Optional[str] = None


class ContextForgeUser(HttpUser):
    """Simulated user for ContextForge API."""

    wait_time = between(0.1, 0.5)  # 100-500ms between requests

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("LOAD_TEST_API_KEY", "")
        self.document_ids: List[str] = []
        self.query_count = 0

    def on_start(self):
        """Initialize user session."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if self.api_key:
            self.client.headers.update({"X-API-Key": self.api_key})

        # Warm up - create a few test documents
        self._create_test_documents(3)

    def _create_test_documents(self, count: int):
        """Create test documents for querying."""
        test_docs = [
            {
                "content": f"Test document {i} about artificial intelligence and machine learning. "
                           f"This document contains information about neural networks, deep learning, "
                           f"and natural language processing concepts. Document ID: {uuid.uuid4()}",
                "metadata": {
                    "source": "load_test",
                    "category": "ai_ml",
                    "tags": ["test", "load_test", f"doc_{i}"]
                }
            }
            for i in range(count)
        ]

        for doc in test_docs:
            try:
                response = self.client.post("/api/v1/documents", json=doc)
                if response.status_code == 201:
                    doc_id = response.json().get("id")
                    if doc_id:
                        self.document_ids.append(doc_id)
            except Exception:
                pass  # Ignore failures during setup

    @task(5)
    def query_rag(self):
        """Query the RAG system - main workload."""
        queries = [
            "What is machine learning?",
            "Explain neural networks",
            "How does deep learning work?",
            "What is natural language processing?",
            "Compare supervised and unsupervised learning",
            "What are transformers in AI?",
            "Explain attention mechanism",
            "What is RAG in LLMs?",
            "How do embeddings work?",
            "What is vector search?"
        ]

        query = random.choice(queries)

        with self.client.post(
            "/api/v1/query",
            json={
                "query": query,
                "top_k": 5,
                "filters": {"category": "ai_ml"},
                "include_sources": True
            },
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "answer" in data and len(data["answer"]) > 10:
                    response.success()
                else:
                    response.failure("Empty or invalid answer")
            else:
                response.failure(f"HTTP {response.status_code}")

        self.query_count += 1

    @task(2)
    def search_documents(self):
        """Search documents directly."""
        search_terms = [
            "machine learning",
            "neural network",
            "deep learning",
            "transformer",
            "attention",
            "embedding",
            "vector",
            "RAG",
            "LLM",
            "AI"
        ]

        term = random.choice(search_terms)

        with self.client.post(
            "/api/v1/search",
            json={
                "query": term,
                "top_k": 10,
                "vector_store": "pgvector"
            },
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "results" in data and len(data["results"]) > 0:
                    response.success()
                else:
                    response.failure("No search results")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def ingest_document(self):
        """Ingest a new document."""
        doc = {
            "content": f"Load test document {uuid.uuid4()} about AI research. "
                       f"Recent advances in {random.choice(['transformers', 'diffusion models', 'RLHF', 'multimodal AI'])} "
                       f"have shown remarkable progress in {random.choice(['text generation', 'image synthesis', 'code generation', 'reasoning'])}.",
            "metadata": {
                "source": "load_test",
                "category": "research",
                "tags": ["load_test", "ingest", str(uuid.uuid4())[:8]]
            }
        }

        with self.client.post(
            "/api/v1/documents",
            json=doc,
            catch_response=True
        ) as response:
            if response.status_code == 201:
                data = response.json()
                if "id" in data:
                    self.document_ids.append(data["id"])
                    response.success()
                else:
                    response.failure("No document ID returned")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def health_check(self):
        """Health check endpoint."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def get_stats(self):
        """Get system statistics."""
        with self.client.get("/api/v1/stats", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


def run_load_test(config: LoadTestConfig) -> Dict:
    """Run the load test and return results."""

    # Create Locust environment
    env = Environment(user_classes=[ContextForgeUser])
    env.create_local_runner()

    # Start test
    print(f"Starting load test: {config.users} users, spawn rate {config.spawn_rate}/s, target {config.target_qps} QPS")
    env.runner.start(config.users, spawn_rate=config.spawn_rate)

    # Parse run time
    run_time_seconds = parse_time(config.run_time)
    start_time = time.time()

    # Track metrics
    max_latency_p99 = 0
    max_error_rate = 0
    min_throughput = float('inf')

    try:
        while time.time() - start_time < run_time_seconds:
            gevent.sleep(5)

            # Get current stats
            stats = env.runner.stats
            total_stats = stats.total

            current_qps = total_stats.total_rps
            current_p99 = total_stats.get_response_time_percentile(0.99)
            current_error_rate = (total_stats.num_failures / max(total_stats.num_requests, 1)) * 100

            print(f"QPS: {current_qps:.1f} | P99: {current_p99:.0f}ms | Errors: {current_error_rate:.2f}% | "
                  f"Requests: {total_stats.num_requests} | Failures: {total_stats.num_failures}")

            max_latency_p99 = max(max_latency_p99, current_p99)
            max_error_rate = max(max_error_rate, current_error_rate)
            min_throughput = min(min_throughput, current_qps)

            # Check if we've hit target QPS
            if current_qps >= config.target_qps * 0.9:
                print(f"✓ Target QPS ({config.target_qps}) achieved!")

    except KeyboardInterrupt:
        print("Load test interrupted")
    finally:
        env.runner.quit()

    # Final stats
    final_stats = env.runner.stats.total

    results = {
        "target_qps": config.target_qps,
        "achieved_qps": final_stats.total_rps,
        "total_requests": final_stats.num_requests,
        "total_failures": final_stats.num_failures,
        "error_rate_percent": (final_stats.num_failures / max(final_stats.num_requests, 1)) * 100,
        "avg_response_time_ms": final_stats.avg_response_time,
        "p50_response_time_ms": final_stats.get_response_time_percentile(0.50),
        "p90_response_time_ms": final_stats.get_response_time_percentile(0.90),
        "p99_response_time_ms": final_stats.get_response_time_percentile(0.99),
        "max_response_time_ms": final_stats.max_response_time,
        "min_throughput_qps": min_throughput if min_throughput != float('inf') else 0,
        "max_latency_p99_ms": max_latency_p99,
        "max_error_rate_percent": max_error_rate,
        "test_duration_seconds": run_time_seconds,
        "passed": (
            final_stats.total_rps >= config.target_qps * 0.8 and
            final_stats.get_response_time_percentile(0.99) < 2000 and
            (final_stats.num_failures / max(final_stats.num_requests, 1)) * 100 < 1.0
        )
    }

    return results


def parse_time(time_str: str) -> int:
    """Parse time string like '5m', '30s', '1h' to seconds."""
    time_str = time_str.strip().lower()
    if time_str.endswith('s'):
        return int(time_str[:-1])
    elif time_str.endswith('m'):
        return int(time_str[:-1]) * 60
    elif time_str.endswith('h'):
        return int(time_str[:-1]) * 3600
    else:
        return int(time_str)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ContextForge Load Test")
    parser.add_argument("--host", required=True, help="Target host URL")
    parser.add_argument("--users", type=int, default=100, help="Number of concurrent users")
    parser.add_argument("--spawn-rate", type=int, default=10, help="Users to spawn per second")
    parser.add_argument("--run-time", default="5m", help="Test duration (e.g., 5m, 30s, 1h)")
    parser.add_argument("--target-qps", type=int, default=1000, help="Target QPS")
    parser.add_argument("--api-key", help="API key for authentication")
    parser.add_argument("--output", help="Output JSON file for results")

    args = parser.parse_args()

    # Set API key in environment
    if args.api_key:
        os.environ["LOAD_TEST_API_KEY"] = args.api_key

    config = LoadTestConfig(
        host=args.host,
        users=args.users,
        spawn_rate=args.spawn_rate,
        run_time=args.run_time,
        target_qps=args.target_qps,
        api_key=args.api_key
    )

    # Run load test
    print(f"ContextForge Load Test")
    print(f"Target: {config.host}")
    print(f"Users: {config.users}, Spawn Rate: {config.spawn_rate}/s")
    print(f"Duration: {config.run_time}, Target QPS: {config.target_qps}")
    print("-" * 50)

    results = run_load_test(config)

    # Print results
    print("\n" + "=" * 50)
    print("LOAD TEST RESULTS")
    print("=" * 50)
    print(f"Target QPS:           {results['target_qps']}")
    print(f"Achieved QPS:         {results['achieved_qps']:.1f}")
    print(f"Total Requests:       {results['total_requests']}")
    print(f"Total Failures:       {results['total_failures']}")
    print(f"Error Rate:           {results['error_rate_percent']:.2f}%")
    print(f"Avg Response Time:    {results['avg_response_time_ms']:.0f}ms")
    print(f"P50 Response Time:    {results['p50_response_time_ms']:.0f}ms")
    print(f"P90 Response Time:    {results['p90_response_time_ms']:.0f}ms")
    print(f"P99 Response Time:    {results['p99_response_time_ms']:.0f}ms")
    print(f"Max Response Time:    {results['max_response_time_ms']:.0f}ms")
    print(f"Min Throughput:       {results['min_throughput_qps']:.1f} QPS")
    print(f"Max P99 Latency:      {results['max_latency_p99_ms']:.0f}ms")
    print(f"Max Error Rate:       {results['max_error_rate_percent']:.2f}%")
    print(f"Test Duration:        {results['test_duration_seconds']}s")
    print(f"PASSED:               {'YES' if results['passed'] else 'NO'}")

    # Save results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")

    # Exit with appropriate code
    sys.exit(0 if results['passed'] else 1)


if __name__ == "__main__":
    main()