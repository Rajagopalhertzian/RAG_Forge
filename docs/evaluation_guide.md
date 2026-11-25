# Evaluation Guide

## Overview

ContextForge includes a comprehensive evaluation framework for measuring RAG system quality across retrieval, generation, chunking, and embedding dimensions. This guide covers golden dataset creation, running evaluations locally, CI/CD integration, and interpreting results.

## Evaluation Architecture

```mermaid
graph TB
    subgraph "Golden Dataset"
        GD[Golden Set<br/>Queries + Relevant Docs]
        GD_VAL[Validation<br/>Diversity, Difficulty]
    end

    subgraph "Evaluation Runner"
        RETRIEVAL[Retrieval Evaluator<br/>MRR, nDCG, Recall, Precision]
        GENERATION[Generation Evaluator<br/>RAGAS, LLM-as-Judge]
        CHUNKING[Chunking Evaluator<br/>Coherence, Boundaries]
        EMBEDDING[Embedding Evaluator<br/>Clustering, Retrieval Corr]
    end

    subgraph "Execution"
        LOCAL[Local: pytest]
        CI[CI: GitHub Actions]
        SCHEDULED[Scheduled: Celery Beat]
    end

    subgraph "Results"
        DB[(PostgreSQL<br/>eval_runs)]
        METRICS[Prometheus<br/>eval_metrics]
        DASHBOARD[Grafana<br/>Eval Dashboards]
        GATE[CI Gate<br/>Pass/Fail]
    end

    GD --> RETRIEVAL
    GD --> GENERATION
    GD_VAL --> GD
    RETRIEVAL --> DB
    GENERATION --> DB
    CHUNKING --> DB
    EMBEDDING --> DB
    LOCAL --> RETRIEVAL
    LOCAL --> GENERATION
    CI --> RETRIEVAL
    CI --> GENERATION
    SCHEDULED --> RETRIEVAL
    SCHEDULED --> GENERATION
    DB --> METRICS
    METRICS --> DASHBOARD
    CI --> GATE
```

---

## Golden Dataset Creation

### What is a Golden Dataset?

A **golden dataset** (or "golden set") is a curated collection of:
- **Queries**: Representative user questions
- **Relevant Documents**: Ground truth relevant document/chunk IDs for each query
- **Expected Answers** (optional): Reference answers for generation evaluation

### Dataset Structure

```json
{
  "name": "golden_set_v1",
  "version": "1.0",
  "description": "Technical documentation QA pairs",
  "queries": [
    {
      "query_id": "q-001",
      "query_text": "How to configure rate limiting in ContextForge?",
      "relevant_docs": ["doc-123", "doc-456"],
      "relevant_chunks": ["chunk-789", "chunk-101"],
      "expected_answer": "Rate limiting is configured via RATE_LIMIT_* environment variables...",
      "difficulty": "easy",
      "category": "configuration"
    }
  ]
}
```

### Creation Process

#### 1. Query Collection
```bash
# Extract from query logs (production)
contextforge export-queries --days 30 --min-frequency 5 > queries.json

# Manual curation from:
# - Support tickets
# - User interviews
# - Documentation FAQs
# - Common search terms
```

#### 2. Relevance Annotation
```bash
# Tool-assisted annotation
contextforge annotate --queries queries.json --output golden_set.json

# Or use the annotation UI (planned)
# http://localhost:8000/admin/annotation
```

#### 3. Quality Validation
```python
# Validate golden set quality
from contextforge.evaluation.retrieval.dataset import validate_golden_set

metrics = validate_golden_set("golden_set.json")
print(f"Query count: {metrics.query_count}")
print(f"Avg relevant docs/query: {metrics.avg_relevant_docs}")
print(f"Category distribution: {metrics.category_dist}")
print(f"Difficulty distribution: {metrics.difficulty_dist}")

# Targets:
# - Minimum 100 queries
# - 3-5 relevant docs per query
# - Balanced categories (config, troubleshooting, how-to, concepts)
# - Mixed difficulty (easy 40%, medium 40%, hard 20%)
```

### Golden Set Best Practices

| Principle | Guideline |
|-----------|-----------|
| **Diversity** | Cover all document types, topics, query intents |
| **Realism** | Use actual user queries, not synthetic |
| **Maintainability** | Version control, changelog, owner |
| **Freshness** | Update quarterly, retire stale queries |
| **Difficulty Mix** | Easy (exact match), Medium (paraphrase), Hard (multi-hop) |
| **Negative Cases** | Include queries with NO relevant docs |

### Storage

Golden datasets stored in PostgreSQL (`eval_runs` table with `eval_type='dataset'`) or as JSON files in `data/golden_sets/`.

```bash
# Register dataset
contextforge dataset register --name golden_set_v1 --file golden_set.json

# List datasets
contextforge dataset list

# Get dataset
contextforge dataset get golden_set_v1
```

---

## Running Evaluations Locally

### Prerequisites

```bash
# Install evaluation dependencies
make dev-install  # Includes eval extras

# Ensure services running
make docker-up    # PostgreSQL, Redis
make migrate      # Database schema
```

### Retrieval Evaluation

```bash
# Run retrieval evaluation
make test-eval

# Or directly with pytest
uv run pytest tests/evaluation/test_retrieval.py -v

# With specific dataset
uv run pytest tests/evaluation/test_retrieval.py -v --dataset golden_set_v1

# Custom k-values
uv run pytest tests/evaluation/test_retrieval.py -v -k "mrr"
```

**Programmatic Usage**:
```python
from contextforge.evaluation.retrieval import evaluate_retrieval, check_thresholds
from contextforge.evaluation.retrieval.dataset import load_golden_set

# Load golden set
golden_set = load_golden_set("golden_set_v1")

# Run evaluation
metrics = evaluate_retrieval(golden_set.queries, k_values=[1, 3, 5, 10, 20])

# Check CI gates
passed, failures = check_thresholds(
    metrics,
    mrr_threshold=0.65,
    latency_p95_threshold=800.0,
    k=10
)

print(f"MRR@10: {metrics.mrr_at_k[10]:.4f}")
print(f"p95 Latency: {metrics.latency_p95:.1f}ms")
print(f"Passed: {passed}")
if not passed:
    for f in failures:
        print(f"  FAIL: {f}")
```

### Generation Evaluation (RAGAS)

```bash
# Run RAGAS evaluation
uv run pytest tests/evaluation/test_generation_ragas.py -v

# With specific metrics
uv run pytest tests/evaluation/test_generation_ragas.py -v -k "faithfulness"
```

**Programmatic Usage**:
```python
from contextforge.evaluation.generation.ragas import evaluate_ragas

metrics = evaluate_ragas(
    queries=golden_set.queries,
    metrics=["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
)

print(f"Faithfulness: {metrics.faithfulness:.4f}")
print(f"Answer Relevancy: {metrics.answer_relevancy:.4f}")
```

### Generation Evaluation (LLM-as-Judge)

```bash
# Run LLM judge evaluation
uv run pytest tests/evaluation/test_generation_judge.py -v
```

**Programmatic Usage**:
```python
from contextforge.evaluation.generation.llm_judge import evaluate_with_llm_judge

metrics = evaluate_with_llm_judge(
    queries=golden_set.queries,
    model="gpt-4",
    criteria=["correctness", "completeness", "conciseness"]
)

print(f"Correctness: {metrics.correctness:.2f}/5.0")
print(f"Completeness: {metrics.completeness:.2f}/5.0")
```

### Chunking Evaluation

```bash
# Evaluate chunking quality
uv run pytest tests/evaluation/test_chunking.py -v
```

### Embedding Evaluation

```bash
# Evaluate embedding quality
uv run pytest tests/evaluation/test_embedding.py -v
```

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/evaluation.yml
name: Evaluation Gates

on:
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday

jobs:
  retrieval-eval:
    name: Retrieval Evaluation
    runs-on: ubuntu-latest
    timeout-minutes: 30
    
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: contextforge
        ports: [5432:5432]
        options: --health-cmd="pg_isready" --health-interval=10s --health-timeout=5s --health-retries=5
      
      redis:
        image: redis:7-alpine
        ports: [6379:6379]
        options: --health-cmd="redis-cli ping" --health-interval=10s --health-timeout=5s --health-retries=5

    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install uv
          uv sync --frozen --all-extras
      
      - name: Run migrations
        run: make migrate
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/contextforge
          REDIS_URL: redis://localhost:6379/0
      
      - name: Start API server
        run: |
          make run &
          sleep 10
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/contextforge
          REDIS_URL: redis://localhost:6379/0
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      
      - name: Run retrieval evaluation
        run: |
          uv run pytest tests/evaluation/test_retrieval.py \
            --dataset golden_set_v1 \
            --junitxml=retrieval-results.xml
        env:
          CONTEXTFORGE_API_URL: http://localhost:8000
          CONTEXTFORGE_API_KEY: ${{ secrets.CONTEXTFORGE_API_KEY }}
      
      - name: Check thresholds
        run: |
          python scripts/check_eval_thresholds.py retrieval-results.xml
      
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: retrieval-eval-results
          path: retrieval-results.xml

  generation-eval:
    name: Generation Evaluation
    runs-on: ubuntu-latest
    # Similar structure...

  eval-gate:
    name: Evaluation Gate
    needs: [retrieval-eval, generation-eval]
    runs-on: ubuntu-latest
    steps:
      - name: Check all evaluations passed
        run: |
          # Fail if any evaluation failed thresholds
          if [ -f "eval_failures.txt" ]; then
            cat eval_failures.txt
            exit 1
          fi
```

### Threshold Checking Script

```python
# scripts/check_eval_thresholds.py
import sys
import xml.etree.ElementTree as ET

def check_junit(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    failures = []
    for testcase in root.findall(".//testcase"):
        for failure in testcase.findall("failure"):
            failures.append(f"{testcase.get('name')}: {failure.text}")
    
    if failures:
        with open("eval_failures.txt", "w") as f:
            f.write("\n".join(failures))
        sys.exit(1)

if __name__ == "__main__":
    check_junit(sys.argv[1])
```

### Branch Protection

Configure branch protection rules in GitHub:
1. Require status checks: `Retrieval Evaluation`, `Generation Evaluation`
2. Require branches to be up to date
3. Dismiss stale reviews on new commits

---

## Interpreting Results

### Retrieval Metrics

| Metric | Range | Good | Excellent | Description |
|--------|-------|------|-----------|-------------|
| **MRR@10** | 0-1 | ≥0.5 | ≥0.7 | Rank of first relevant result |
| **nDCG@10** | 0-1 | ≥0.5 | ≥0.7 | Ranking quality with position discount |
| **Recall@10** | 0-1 | ≥0.7 | ≥0.9 | Fraction of relevant found |
| **Precision@10** | 0-1 | ≥0.1 | ≥0.3 | Fraction of results relevant |
| **Latency p95** | ms | <800 | <300 | 95th percentile latency |

### Threshold Justification

**MRR@10 ≥ 0.65**: Based on user studies showing:
- MRR < 0.5: Users abandon search, try different queries
- MRR 0.5-0.65: Acceptable but frustrating
- MRR > 0.65: Good user experience, relevant result typically in top 3

**Latency p95 < 800ms**: Based on:
- 200ms: Perceived as instant
- 500ms: Noticeable but acceptable
- 800ms: Upper bound for "fast" feeling
- >1s: Users perceive as slow

### Generation Metrics (RAGAS)

| Metric | Range | Good | Excellent | Description |
|--------|-------|------|-----------|-------------|
| **Faithfulness** | 0-1 | ≥0.7 | ≥0.9 | Answer grounded in context |
| **Answer Relevancy** | 0-1 | ≥0.7 | ≥0.9 | Answer addresses question |
| **Context Precision** | 0-1 | ≥0.6 | ≥0.8 | Relevant context ranked high |
| **Context Recall** | 0-1 | ≥0.7 | ≥0.9 | All relevant context retrieved |

### LLM-as-Judge Scores

| Score | Meaning |
|-------|---------|
| 5 | Perfect - complete, correct, concise |
| 4 | Minor issues - slightly verbose or missing minor detail |
| 3 | Acceptable - correct but incomplete or verbose |
| 2 | Significant issues - partially incorrect or missing key info |
| 1 | Poor - mostly incorrect or irrelevant |

**Target**: Average ≥ 4.0 across criteria

### Dashboard Interpretation

#### Retrieval Dashboard
- **Trend lines**: MRR@10 over time (should be stable or improving)
- **Latency heatmap**: p50/p95/p99 by hour
- **Failure queries**: Queries consistently below threshold

#### Generation Dashboard
- **RAGAS radar chart**: Faithfulness, Relevancy, Precision, Recall
- **Judge score distribution**: Histogram of 1-5 scores
- **Error analysis**: Common failure patterns

---

## Advanced Topics

### A/B Testing Evaluations

```python
# Compare two configurations
from contextforge.evaluation.retrieval import evaluate_retrieval

# Config A: hybrid search
metrics_a = evaluate_retrieval(queries, config={"search_type": "hybrid", "alpha": 0.5})

# Config B: vector only
metrics_b = evaluate_retrieval(queries, config={"search_type": "vector"})

# Statistical significance
from scipy import stats
mrr_a = [q["mrr_at_10"] for q in metrics_a.per_query]
mrr_b = [q["mrr_at_10"] for q in metrics_b.per_query]
t_stat, p_value = stats.ttest_rel(mrr_a, mrr_b)
print(f"p-value: {p_value:.4f}")  # < 0.05 = significant
```

### Regression Detection

```python
# Compare current run to baseline
from contextforge.storage.repositories.eval_run import EvalRunRepository

repo = EvalRunRepository()
baseline = repo.get_latest_completed("retrieval", "golden_set_v1")
current = repo.get_latest_completed("retrieval", "golden_set_v1", exclude=baseline.id)

mrr_diff = current.metrics["mrr_at_10"] - baseline.metrics["mrr_at_10"]
latency_diff = current.metrics["latency_p95"] - baseline.metrics["latency_p95"]

if mrr_diff < -0.02:  # 2% regression
    alert("MRR regression detected!")
if latency_diff > 100:  # 100ms regression
    alert("Latency regression detected!")
```

### Custom Metrics

```python
# Add custom business metric
from contextforge.evaluation.retrieval.metrics import RetrievalMetrics

def business_relevance_score(query, results):
    """Custom metric: % results from premium content"""
    premium = sum(1 for r in results if r.metadata.get("tier") == "premium")
    return premium / len(results) if results else 0

# Register custom metric
# (Add to evaluation runner)
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Low MRR | Poor chunking/embeddings | Try semantic/hierarchical chunking, better embedding model |
| High latency | No HNSW index / large dataset | Create HNSW index, add read replicas |
| RAGAS failures | LLM API errors | Check API keys, rate limits, model availability |
| Flaky tests | Race conditions | Increase timeouts, use deterministic seeds |
| OOM in eval | Large golden set | Batch evaluation, stream results |

### Debugging Commands

```bash
# Verbose evaluation output
uv run pytest tests/evaluation/test_retrieval.py -v -s --tb=long

# Single test with debug
uv run pytest tests/evaluation/test_retrieval.py::test_mrr_at_10 -v -s

# Profile evaluation
uv run python -m cProfile -o eval.prof -m pytest tests/evaluation/test_retrieval.py
```

---

## Maintenance

### Golden Set Updates

```bash
# Quarterly review checklist
# 1. Add new queries from production logs
# 2. Remove obsolete queries (deleted docs, deprecated features)
# 3. Re-annotate relevance for changed documents
# 4. Validate difficulty distribution
# 5. Version bump (v1 → v2)
```

### Threshold Tuning

```bash
# Adjust thresholds based on business impact
# Current: MRR@10 ≥ 0.65, p95 < 800ms
# If user complaints increase: tighten
# If false positives block good PRs: loosen

# Document changes in CHANGELOG.md
```

---

## References

- [RAGAS Paper](https://arxiv.org/abs/2309.15217)
- [MRR/nDCG/Recall Definitions](https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval))
- [LLM-as-Judge Best Practices](https://arxiv.org/abs/2306.05685)
- [ContextForge Evaluation Code](src/contextforge/evaluation/)