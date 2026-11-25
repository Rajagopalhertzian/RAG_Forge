# ContextForge API Reference

## Overview

The ContextForge API is a RESTful interface built with FastAPI, providing endpoints for document ingestion, querying, evaluation, and system monitoring. All endpoints return JSON and follow OpenAPI 3.0 specification.

**Base URL**: `http://localhost:8000` (development) / `https://api.contextforge.example.com` (production)

**Authentication**: API Key via `X-API-Key` header

**Content Type**: `application/json`

---

## Quick Reference

| Category | Endpoints |
|----------|-----------|
| **Health** | `GET /health`, `GET /metrics` |
| **Ingestion** | `POST /api/v1/ingestion`, `GET /api/v1/ingestion/{job_id}`, `GET /api/v1/ingestion`, `DELETE /api/v1/ingestion/{job_id}` |
| **Documents** | `GET /api/v1/documents`, `GET /api/v1/documents/{doc_id}`, `DELETE /api/v1/documents/{doc_id}` |
| **Query** | `POST /api/v1/query`, `POST /api/v1/query/vector`, `POST /api/v1/query/keyword` |
| **Evaluation** | `POST /api/v1/eval/retrieval`, `POST /api/v1/eval/generation`, `GET /api/v1/eval/runs`, `GET /api/v1/eval/runs/{run_id}` |

---

## Authentication

All API endpoints (except `/health`, `/metrics`, `/docs`, `/redoc`) require authentication via API key:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/v1/ingestion
```

API keys are managed via environment variable `SECRET_KEY` and validated against hashed storage (implementation in middleware).

---

## Health & Monitoring

### Health Check
```http
GET /health
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "app": "contextforge",
  "version": "0.1.0",
  "env": "development"
}
```

### Prometheus Metrics
```http
GET /metrics
```

**Response**: Prometheus exposition format (text/plain)
```
http_requests_total{method="GET",endpoint="/health",status="200"} 1.0
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.1"} 1.0
...
```

---

## Ingestion Endpoints

### Start Ingestion Job
```http
POST /api/v1/ingestion
```

**Request Body**:
```json
{
  "source_type": "file",
  "source_id": "doc-123",
  "source_url": "https://example.com/doc.pdf",
  "title": "Optional Document Title",
  "content": "Document text content (for text source_type)",
  "strategy": "semantic",
  "embedding_provider": "openai",
  "embedding_model": "text-embedding-3-large",
  "metadata": {
    "author": "John Doe",
    "tags": ["technical", "api"]
  },
  "chunk_size": 512,
  "chunk_overlap": 50
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source_type` | string | Yes | - | `file`, `url`, `text`, `notion`, `confluence`, `github`, `slack` |
| `source_id` | string | Yes | - | Unique identifier within source |
| `source_url` | string | No | null | Original URL for reference |
| `title` | string | No | null | Document title |
| `content` | string | Conditional | - | Required for `text` source_type |
| `strategy` | string | No | `semantic` | `semantic`, `hierarchical`, `code`, `fixed` |
| `embedding_provider` | string | No | `openai` | `openai`, `azure`, `bedrock`, `local` |
| `embedding_model` | string | No | `text-embedding-3-large` | Model name |
| `metadata` | object | No | `{}` | Custom metadata |
| `chunk_size` | integer | No | 512 | Override default chunk size |
| `chunk_overlap` | integer | No | 50 | Override default overlap |

**Response** (202 Accepted):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Ingestion job queued"
}
```

### Get Job Status
```http
GET /api/v1/ingestion/{job_id}
```

**Response** (200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "document_id": "550e8400-e29b-41d4-a716-446655440001",
  "source_type": "file",
  "source_id": "doc-123",
  "status": "completed",
  "strategy": "semantic",
  "embedding_provider": "openai",
  "embedding_model": "text-embedding-3-large",
  "chunk_count": 42,
  "error_message": null,
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:30:45Z",
  "created_at": "2024-01-15T10:29:55Z"
}
```

**Status Values**: `pending`, `processing`, `completed`, `failed`

### List Ingestion Jobs
```http
GET /api/v1/ingestion?page=1&page_size=20&status=completed&source_type=file
```

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number |
| `page_size` | integer | 20 | Items per page (max 100) |
| `status` | string | - | Filter by status |
| `source_type` | string | - | Filter by source type |

**Response** (200 OK):
```json
{
  "items": [
    { "job_id": "...", "status": "completed", ... }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

### Cancel Ingestion Job
```http
DELETE /api/v1/ingestion/{job_id}
```

**Response** (200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "Job cancelled successfully"
}
```

---

## Document Endpoints

### List Documents
```http
GET /api/v1/documents?page=1&page_size=20&source_type=file
```

**Query Parameters**: Same as job listing

**Response** (200 OK):
```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "source_type": "file",
      "source_id": "doc-123",
      "title": "API Documentation",
      "chunk_count": 42,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

### Get Document with Chunks
```http
GET /api/v1/documents/{doc_id}?include_chunks=true&chunk_limit=10
```

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_chunks` | boolean | true | Include chunk details |
| `chunk_limit` | integer | 50 | Max chunks to return |

**Response** (200 OK):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "source_type": "file",
  "source_id": "doc-123",
  "title": "API Documentation",
  "content": "Full document content...",
  "metadata": { "author": "John Doe" },
  "content_hash": "sha256:...",
  "chunk_count": 42,
  "chunks": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "chunk_index": 0,
      "content": "First chunk content...",
      "token_count": 128,
      "strategy": "semantic",
      "embedding_model": "text-embedding-3-large",
      "embedding_provider": "openai"
    }
  ],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### Delete Document
```http
DELETE /api/v1/documents/{doc_id}
```

**Response** (200 OK):
```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440001",
  "message": "Document and associated chunks deleted"
}
```

---

## Query Endpoints

### Hybrid Search (Recommended)
```http
POST /api/v1/query
```

**Request Body**:
```json
{
  "query": "How to configure rate limiting?",
  "top_k": 10,
  "filters": {
    "source_type": "file",
    "tags": ["api", "config"],
    "date_from": "2024-01-01",
    "date_to": "2024-12-31"
  },
  "score_threshold": 0.7,
  "search_type": "hybrid",
  "alpha": 0.5
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query text |
| `top_k` | integer | No | 10 | Number of results (max 100) |
| `filters` | object | No | `{}` | Metadata filters |
| `score_threshold` | number | No | 0.0 | Minimum similarity score |
| `search_type` | string | No | `hybrid` | `hybrid`, `vector`, `keyword` |
| `alpha` | number | No | 0.5 | Hybrid weight (0=keyword, 1=vector) |

**Response** (200 OK):
```json
{
  "query": "How to configure rate limiting?",
  "results": [
    {
      "chunk_id": "550e8400-e29b-41d4-a716-446655440010",
      "document_id": "550e8400-e29b-41d4-a716-446655440001",
      "content": "Rate limiting is configured via...",
      "score": 0.92,
      "metadata": {
        "source_type": "file",
        "chunk_index": 3,
        "strategy": "semantic"
      }
    }
  ],
  "total_results": 42,
  "latency_ms": 45,
  "search_type": "hybrid"
}
```

### Vector-Only Search
```http
POST /api/v1/query/vector
```

**Request Body**: Same as hybrid search, but `search_type` ignored

**Use Case**: When you want pure semantic similarity without keyword matching

### Keyword-Only Search
```http
POST /api/v1/query/keyword
```

**Request Body**: Same as hybrid search, but uses PostgreSQL tsvector/BM25

**Use Case**: Exact phrase matching, known-term lookup

---

## Evaluation Endpoints

### Run Retrieval Evaluation
```http
POST /api/v1/eval/retrieval
```

**Request Body**:
```json
{
  "name": "weekly-retrieval-eval",
  "dataset": "golden_set_v1",
  "k_values": [1, 3, 5, 10, 20],
  "config": {
    "search_type": "hybrid",
    "alpha": 0.5
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Evaluation run name |
| `dataset` | string | Yes | - | Golden dataset identifier |
| `k_values` | array | No | [1,3,5,10,20] | k values for metrics |
| `config` | object | No | `{}` | Search configuration |

**Response** (202 Accepted):
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440020",
  "status": "running",
  "message": "Evaluation started"
}
```

### Run Generation Evaluation
```http
POST /api/v1/eval/generation
```

**Request Body**:
```json
{
  "name": "generation-quality-eval",
  "dataset": "golden_set_v1",
  "metrics": ["faithfulness", "answer_relevancy", "context_precision", "context_recall"],
  "llm_judge_config": {
    "model": "gpt-4",
    "criteria": ["correctness", "completeness", "conciseness"]
  }
}
```

### List Evaluation Runs
```http
GET /api/v1/eval/runs?page=1&page_size=20&eval_type=retrieval
```

**Response** (200 OK):
```json
{
  "items": [
    {
      "run_id": "550e8400-e29b-41d4-a716-446655440020",
      "name": "weekly-retrieval-eval",
      "eval_type": "retrieval",
      "dataset": "golden_set_v1",
      "status": "completed",
      "metrics": {
        "mrr_at_10": 0.68,
        "ndcg_at_10": 0.72,
        "recall_at_10": 0.85,
        "latency_p95_ms": 650
      },
      "created_at": "2024-01-15T10:00:00Z",
      "completed_at": "2024-01-15T10:05:00Z"
    }
  ],
  "total": 25,
  "page": 1,
  "page_size": 20
}
```

### Get Evaluation Results
```http
GET /api/v1/eval/runs/{run_id}
```

**Response** (200 OK):
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440020",
  "name": "weekly-retrieval-eval",
  "eval_type": "retrieval",
  "dataset": "golden_set_v1",
  "config": { "search_type": "hybrid", "alpha": 0.5 },
  "metrics": {
    "mrr_at_k": { "1": 0.45, "3": 0.58, "5": 0.63, "10": 0.68, "20": 0.71 },
    "ndcg_at_k": { "1": 0.42, "3": 0.55, "5": 0.61, "10": 0.67, "20": 0.70 },
    "recall_at_k": { "1": 0.35, "3": 0.55, "5": 0.68, "10": 0.85, "20": 0.92 },
    "precision_at_k": { "1": 0.35, "3": 0.18, "5": 0.14, "10": 0.085, "20": 0.046 },
    "latency_p50_ms": 120,
    "latency_p95_ms": 650,
    "latency_p99_ms": 1200,
    "total_queries": 100
  },
  "threshold_check": {
    "passed": true,
    "failures": []
  },
  "status": "completed",
  "created_at": "2024-01-15T10:00:00Z",
  "completed_at": "2024-01-15T10:05:00Z"
}
```

---

## Error Responses

All errors follow a consistent format:

```json
{
  "error": "ErrorType",
  "message": "Human-readable description",
  "details": { "field": "additional context" },
  "request_id": "550e8400-e29b-41d4-a716-446655440030"
}
```

### HTTP Status Codes

| Code | Error Type | Description |
|------|------------|-------------|
| 400 | ValidationError | Invalid request body |
| 401 | Unauthorized | Missing or invalid API key |
| 404 | NotFoundError | Resource not found |
| 422 | ValidationError | Pydantic validation failed |
| 429 | RateLimitError | Rate limit exceeded |
| 500 | InternalServerError | Unexpected server error |
| 503 | ServiceUnavailable | Dependency unavailable |

### Rate Limit Headers

When rate limiting is enabled:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1705320000
Retry-After: 30 (when limit exceeded)
```

---

## Request/Response Examples

### Complete Ingestion Flow
```bash
# 1. Start ingestion
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/ingestion \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "source_type": "text",
    "source_id": "example-1",
    "content": "ContextForge is an enterprise RAG platform...",
    "strategy": "semantic"
  }' | jq -r '.job_id')

# 2. Poll for completion
while true; do
  STATUS=$(curl -s -H "X-API-Key: your-key" \
    http://localhost:8000/api/v1/ingestion/$JOB_ID | jq -r '.status')
  echo "Status: $STATUS"
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && exit 1
  sleep 2
done

# 3. Query the ingested content
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"query": "What is ContextForge?", "top_k": 5}'
```

### Evaluation with CI Gate
```bash
# Run evaluation
RUN_ID=$(curl -s -X POST http://localhost:8000/api/v1/eval/retrieval \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"name": "ci-gate", "dataset": "golden_set"}' | jq -r '.run_id')

# Wait and check results
sleep 30
curl -s -H "X-API-Key: your-key" \
  http://localhost:8000/api/v1/eval/runs/$RUN_ID | jq '.threshold_check'
# {"passed": true, "failures": []}
```

---

## OpenAPI Specification

The full OpenAPI 3.0 specification is available at:
- **JSON**: `GET /openapi.json`
- **Swagger UI**: `GET /docs` (development only)
- **ReDoc**: `GET /redoc` (development only)

### Generating Client SDKs

```bash
# Python client
openapi-python-client generate --url http://localhost:8000/openapi.json

# TypeScript client
openapi-typescript-codegen -i http://localhost:8000/openapi.json -o ./client

# Go client
oapi-codegen -generate types,client -package contextforge http://localhost:8000/openapi.json
```

---

## Versioning

API versioning via URL path: `/api/v1/`

- **v1**: Current stable version
- Breaking changes require new version (v2)
- Deprecation policy: 6 months notice, documented in changelog

---

## Rate Limits

Default limits (configurable via environment):
- **Requests/minute**: 60
- **Burst**: 10
- **Scope**: Per API key

Exceeding limits returns 429 with `Retry-After` header.

---

## Webhooks (Planned)

Future support for async notifications:
- `ingestion.completed`
- `ingestion.failed`
- `evaluation.completed`
- `evaluation.threshold_failed`

Configure via API or dashboard.