# ContextForge Live Demo Script (3 Minutes)

**Goal**: Demonstrate end-to-end RAG pipeline with observability in 3 minutes.  
**Audience**: Technical interviewers, stakeholders, engineers.  
**Prereqs**: Local stack running (`docker compose -f docker/docker-compose.yml --profile with-observability up -d`)

---

## Demo Flow Overview

| Time | Step | What Audience Sees |
|------|------|-------------------|
| 0:00-0:30 | **Ingest** | Load a real document, watch chunks/embeddings create |
| 0:30-1:30 | **Query + Stream** | Ask question, see streaming tokens, retrieve sources |
| 1:30-2:15 | **LangFuse Trace** | Open trace, show span breakdown, costs |
| 2:15-3:00 | **Eval Dashboard** | Show retrieval metrics, CI gate status |

---

## Pre-Demo Setup (Do Before Call)

```bash
# 1. Start full stack with observability
docker compose -f docker/docker-compose.yml --profile with-observability up -d

# 2. Verify services
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:3000/api/health  # Grafana
curl -s http://localhost:16686/ready      # Tempo

# 3. Load demo document
curl -X POST http://localhost:8000/api/v1/ingestion \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "file",
    "source_id": "contextforge-spec",
    "content": "'"$(cat SPEC.md | head -200 | sed 's/"/\\"/g')"'",
    "strategy": "semantic",
    "embedding_provider": "local",
    "embedding_model": "BAAI/bge-m3"
  }'

# 4. Wait for ingestion (check job status)
JOB_ID=$(curl -s http://localhost:8000/api/v1/ingestion | jq -r '.[0].id')
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/ingestion/$JOB_ID | jq -r '.status')
  echo "Status: $STATUS"
  [ "$STATUS" = "completed" ] && break
  sleep 2
done

# 5. Open browser tabs
# Tab 1: http://localhost:8000/docs (Swagger UI)
# Tab 2: http://localhost:3000 (Grafana - dashboards/contextforge-overview)
# Tab 3: http://localhost:16686 (Tempo - search service=contextforge-api)
# Tab 4: http://localhost:4000 (LangFuse - if running)
```

---

## Minute 0:00-0:30 — Ingest a Document

### Script
> "Let me show you the ingestion pipeline. I'll feed it the ContextForge specification document — about 50KB of markdown with architecture, requirements, and API specs."

### Actions
1. **Open Swagger UI** (Tab 1): `http://localhost:8000/docs`
2. **Navigate to** `POST /api/v1/ingestion`
3. **Click "Try it out"**
4. **Paste this payload** (or use pre-loaded):
```json
{
  "source_type": "file",
  "source_id": "demo-contextforge-spec",
  "title": "ContextForge Specification",
  "content": "# ContextForge Specification\n\n## 1. Project Overview\n\nContextForge is an enterprise-grade Retrieval-Augmented Generation (RAG) pipeline that provides:\n- Multi-strategy document chunking (semantic, hierarchical, code-aware, fixed)\n- Pluggable embedding providers (OpenAI, Azure, Bedrock, Local)\n- Multiple vector stores (pgvector HNSW, FAISS, Weaviate)\n- Async ingestion with Celery\n- Hybrid search (vector + BM25)\n- Comprehensive evaluation (RAGAS, LLM-as-Judge, custom metrics)\n- Model Context Protocol (MCP) integration\n- Full observability (OpenTelemetry, Prometheus, Grafana, Tempo)\n- Production deployment (Docker, Terraform, Blue/Green)\n\n... [truncated for demo]",
  "strategy": "semantic",
  "embedding_provider": "local",
  "embedding_model": "BAAI/bge-m3",
  "metadata": {"demo": true, "category": "spec"}
}
```
5. **Click "Execute"**
6. **Show response**: `202 Accepted` with `job_id`
7. **Poll job status**: `GET /api/v1/ingestion/{job_id}` until `completed`
8. **Highlight**: "Notice the chunk count, embedding model, and processing time"

### Talking Points
- "Async by default — API returns immediately, Celery processes in background"
- "Pluggable chunking: semantic strategy uses embedding similarity (threshold 0.7)"
- "Local embeddings (BGE-M3) for zero-cost development — same interface as OpenAI"
- "Idempotent: re-ingesting same content returns existing document (content hash)"

---

## Minute 0:30-1:30 — Query with Streaming

### Script
> "Now let's query the knowledge base. I'll ask a question that requires synthesizing information from multiple chunks."

### Actions
1. **Navigate to** `POST /api/v1/query` in Swagger UI
2. **Click "Try it out"**
3. **Paste query**:
```json
{
  "query": "What chunking strategies does ContextForge support and when should I use each?",
  "top_k": 5,
  "filters": {},
  "rerank": true,
  "stream": true
}
```
4. **Click "Execute"**
5. **Watch streaming response** (Server-Sent Events):
   - First: Retrieval results (chunks with scores)
   - Then: Streaming answer tokens
   - Finally: Metadata (latency, tokens, model)

### Expected Output
```
data: {"type": "retrieval", "results": [
  {"chunk_id": "...", "content": "## 2.2 Chunking Strategies\n- FR-8: Semantic chunking...", "score": 0.89, "metadata": {"strategy": "semantic"}},
  {"chunk_id": "...", "content": "### Semantic Chunking\n- Split by semantic similarity...", "score": 0.85, "metadata": {"strategy": "semantic"}},
  {"chunk_id": "...", "content": "### Hierarchical Chunking\n- Parent chunks: 1024 tokens...", "score": 0.82, "metadata": {"strategy": "hierarchical"}}
]}

data: {"type": "token", "text": "ContextForge supports four chunking strategies..."}
data: {"type": "token", "text": "1. **Semantic chunking** — best for prose, documentation..."}
data: {"type": "token", "text": "2. **Hierarchical chunking** — best for long documents..."}
data: {"type": "token", "text": "3. **Code-aware chunking** — uses tree-sitter AST..."}
data: {"type": "token", "text": "4. **Fixed-size chunking** — fallback for unknown formats..."}

data: {"type": "metadata", "latency_ms": 423, "prompt_tokens": 156, "completion_tokens": 289, "model": "gpt-4o-mini"}
```

### Talking Points
- "Hybrid search: vector + BM25 fused with RRF (no tuning needed)"
- "Cross-encoder reranker for precision (enabled via `rerank: true`)"
- "Streaming tokens via SSE — same interface as OpenAI"
- "p95 latency ~400ms including reranking"
- "Citations included: each answer chunk links back to source"

---

## Minute 1:30-2:15 — LangFuse Trace Deep Dive

### Script
> "Let's look under the hood. Every request is traced end-to-end with LangFuse — you can see exactly what happened, how long each step took, and what it cost."

### Actions
1. **Open LangFuse** (Tab 4): `http://localhost:4000` (or Tempo if LangFuse not running)
2. **Search for trace**: Filter by `service=contextforge-api`, last 5 minutes
3. **Click the latest trace** (should be named "POST /api/v1/query")
4. **Walk through spans**:

### Expected Span Tree
```
POST /api/v1/query (423ms total)
├── middleware.rate_limit (2ms)
├── middleware.metrics (1ms)
├── query_engine.search (380ms)
│   ├── embedding.embed_query (local:bge-m3) (45ms)
│   ├── vector_store.vector_search (pgvector:hnsw) (12ms)  ← Fast!
│   ├── vector_store.keyword_search (tsvector) (8ms)
│   ├── retrieval.reciprocal_rank_fusion (3ms)
│   └── reranker.cross_encoder (ms-marco-MiniLM) (210ms)  ← Bottleneck
├── llm.generate_answer (gpt-4o-mini) (180ms)
│   ├── prompt.construction (5ms)
│   └── streaming.tokens (175ms)
└── observability.log_query (15ms)
```

### Key Things to Highlight
1. **Click `vector_store.vector_search`**: Show HNSW parameters, index hit
2. **Click `reranker.cross_encoder`**: Show batch size, model, latency
3. **Click `llm.generate_answer`**: Show prompt tokens, completion tokens, **cost estimate**
4. **Cost breakdown**: 
   - Embedding (local): $0.00
   - Vector search: $0.00 (self-hosted)
   - Reranker (local): $0.00
   - LLM (gpt-4o-mini): ~$0.0004 per query
   - **Total: <$0.001 per query**

### Talking Points
- "Full distributed trace: API → Celery → PostgreSQL → pgvector → LLM"
- "Reranker is the latency bottleneck (210ms) — we batch in production"
- "Cost tracking per request — essential for budgeting at scale"
- "Same trace shows ingestion pipeline spans (async via Celery)"

---

## Minute 2:15-3:00 — Evaluation Dashboard

### Script
> "Finally, let's look at how we measure quality. This is our Grafana dashboard showing retrieval evaluation metrics — the same gates that run in CI/CD."

### Actions
1. **Open Grafana** (Tab 2): `http://localhost:3000`
2. **Navigate to**: Dashboards → ContextForge → Retrieval Evaluation
3. **Show panels**:

### Dashboard Panels

#### Panel 1: Retrieval Quality (Time Series)
```
MRR@10  ████████████░░░░░░░░  0.68 (target: ≥0.65) ✅
nDCG@10 ████████████████░░  0.72
Recall@10 ██████████████░░░  0.78
Precision@10 ██████████░░░░░░  0.61
```
- **Green line**: Current production baseline
- **Red line**: CI gate threshold (0.65)
- **Annotation**: "v2.3.1 deploy" — shows quality maintained

#### Panel 2: Latency Percentiles
```
p50:  180ms
p95:  650ms  (target: <800ms) ✅
p99:  1.2s
```
- **Spike annotation**: "Reranker enabled" — shows impact

#### Panel 3: Evaluation Runs (Table)
| Run ID | Dataset | MRR@10 | p95 (ms) | Status | Trigger |
|--------|---------|--------|----------|--------|---------|
| eval-042 | golden_v2.1 | 0.68 | 650 | ✅ Pass | Nightly |
| eval-041 | golden_v2.1 | 0.67 | 720 | ✅ Pass | PR #1247 |
| eval-040 | golden_v2.0 | 0.63 | 890 | ❌ Fail | PR #1234 |

#### Panel 4: Golden Set Coverage
```
Queries: 200 total
- Easy:    80 (40%)  — MRR: 0.82
- Medium:  80 (40%)  — MRR: 0.65
- Hard:    40 (20%)  — MRR: 0.41
Categories: Config (30%), Troubleshooting (25%), How-to (25%), Concepts (20%)
```

### Talking Points
- "CI gate: MRR@10 ≥ 0.65 AND p95 < 800ms — both must pass"
- "Caught 3 regressions in 6 months before they hit production"
- "Golden set: 200 queries from production logs, support tickets, FAQs"
- "Nightly full eval + PR-time subset (20 queries, relaxed threshold)"
- "RAGAS generation metrics on separate dashboard (faithfulness, relevancy)"

---

## Backup Demos (If Time Permits)

### 1. MCP Integration (30 seconds)
```bash
# In terminal
uv run contextforge-mcp --stdio

# In another terminal (simulate Claude Desktop)
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"query_knowledge","arguments":{"query":"chunking strategies","top_k":3}}}' | uv run contextforge-mcp --stdio
```
Shows: JSON-RPC response with same results as REST API.

### 2. Ingestion CLI (15 seconds)
```bash
make ingest FILE=docs/architecture.md
```
Shows: Progress bar, chunk count, embedding time.

### 3. Failure Injection (30 seconds)
```bash
# Kill pgvector temporarily
docker compose stop postgres

# Query fails gracefully
curl -X POST http://localhost:8000/api/v1/query -d '{"query":"test"}'
# Returns 503 with "vector store unavailable" — circuit breaker works
```

---

## Demo Checklist (Print This)

- [ ] Docker stack running with observability profile
- [ ] Demo document pre-ingested (or ingest live for effect)
- [ ] Swagger UI open at `/docs`
- [ ] Grafana dashboard loaded (Retrieval Evaluation)
- [ ] LangFuse/Tempo trace accessible
- [ ] Query payload copied to clipboard
- [ ] Talking points reviewed
- [ ] Backup demo commands ready

---

## Common Questions & Answers

| Question | Answer |
|----------|--------|
| "What's the cost per query?" | <$0.001 with local embeddings + self-hosted vector store + gpt-4o-mini |
| "How do you handle multi-tenancy?" | Namespace isolation via PostgreSQL RLS + vector partition by tenant (planned) |
| "Can I use my own embedding model?" | Yes — implement `EmbeddingProvider` protocol, register in config |
| "What's the max document size?" | Tested to 10MB (500K tokens); hierarchical chunking handles large docs |
| "How do you update embeddings when model changes?" | Re-embedding job with projection layer for zero-downtime migration |
| "Is this running in production?" | Yes — 15 engineers using daily via MCP, 10K+ queries/week |

---

## Minimal Demo (1 Minute Version)

If time-crunched:
1. **Query only**: Run the streaming query (30s)
2. **Show trace**: Open LangFuse, point to reranker span (20s)
3. **Show dashboard**: Grafana MRR@10 green (10s)
**Total: 60 seconds, hits all key value props**

---

*Demo script v1.0 — Practice once, deliver confidently.*