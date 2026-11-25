# Resume Bullets - ContextForge

## 7 STAR-Format Bullets (from SPEC Section 11)

### For Senior/Staff ML Engineer Roles

---

### 1. Multi-Strategy Chunking Pipeline
**Built a pluggable chunking framework (semantic, hierarchical, code-aware, fixed-size) that improved retrieval MRR@10 by 40% (0.46→0.65) and reduced embedding costs 30% via hierarchical parent/child reuse.**

**Technical Details**: Abstract `ChunkingStrategy` protocol with 4 implementations; sentence-transformers for semantic similarity (threshold 0.7); tree-sitter AST parsing for 6+ languages; recursive splitting with configurable separators; config-driven per-document-type selection.

**Metrics**: MRR@10 0.46→0.65 | Embedding cost -30% | 4 strategies production-ready

---

### 2. Pluggable Embedding Provider Architecture
**Designed unified embedding abstraction supporting OpenAI, Azure OpenAI, AWS Bedrock, and local sentence-transformers with automatic dimension detection, batch processing (32), exponential backoff retry, and circuit breaker — enabling zero-downtime provider switching and 60% dev cost reduction.**

**Technical Details**: `EmbeddingProvider` protocol with provider-specific clients; automatic model dimension inference; configurable batch sizing; 3-attempt exponential backoff; circuit breaker (failure threshold=5, timeout=60s, half-open); local BGE-M3 for development.

**Metrics**: Zero-downtime switching | Dev cost -60% | p95 latency <100ms | 4 providers

---

### 3. Production RAG Evaluation Framework with CI Gates
**Built comprehensive evaluation framework (retrieval: MRR/nDCG/Recall/Precision/latency; generation: RAGAS + LLM-as-Judge; chunking/embedding quality) with golden dataset management and GitHub Actions CI gates failing PRs if MRR@10<0.65 or p95>800ms.**

**Technical Details**: Retrieval metrics module (MRR@k, nDCG@k, Recall@k, Precision@k, p50/p95/p99); RAGAS integration (faithfulness, answer_relevancy, context_precision/recall); custom LLM-judge (correctness, completeness, conciseness); pytest integration; GitHub Actions workflow with threshold enforcement.

**Metrics**: 3 regressions caught/6mo | Baseline MRR@10=0.68, p95=650ms | Weekly deployments | 200-query golden set

---

### 4. MCP Server for Claude Desktop/Cursor Integration
**Implemented Model Context Protocol server with 6 tools (ingest, query, list, retrieval-eval, generation-eval, get-results) using JSON Schema validation, API key auth, stdio transport — adopted by 15+ engineers, reducing query iteration from 5min to 30sec.**

**Technical Details**: MCP stdio transport; 6 tool definitions with strict JSON Schema; API key authentication via env; PyPI package for one-line install; Claude Desktop/Cursor config examples; error handling with MCP error codes.

**Metrics**: 15+ engineer adoption | Iteration time 5min→30sec | 6 tools | One-line install

---

### 5. Multi-Vector Store Abstraction with pgvector HNSW Optimization
**Created unified `VectorStore` protocol (upsert, search, delete, hybrid_search) with pgvector adapter (HNSW M=16, ef_construction=64), FAISS adapter for local dev, and Weaviate ready — achieving 10x faster search vs IVFFlat (80ms→8ms p95) with seamless local-to-prod parity.**

**Technical Details**: `VectorStore` protocol; pgvector HNSW index creation; async batch upserts (100); connection pooling (asyncpg); FAISS HNSW32 with disk persistence; Weaviate GraphQL adapter; hybrid search via RRF (k=60).

**Metrics**: p95 80ms→8ms (10x) | Local-prod parity | 3 backends | Hybrid search

---

### 6. Full Observability Stack (OpenTelemetry, Prometheus, Grafana, Tempo)
**Implemented end-to-end observability: structured JSON logging with request IDs; OpenTelemetry auto-instrumentation (FastAPI, Celery, SQLAlchemy, Redis); custom Prometheus metrics (business + RED); Grafana dashboards for RAG pipeline; Tempo distributed tracing (7-day retention) — reducing MTTD from 45min to 5min.**

**Technical Details**: structlog JSON logging; OTel auto-instrumentation + manual spans for ingestion stages; Prometheus metrics (http_requests_total, ingestion_jobs_total, chunk_count, embedding_duration_seconds); Grafana dashboards (pipeline health, ingestion throughput, vector search); Tempo trace storage.

**Metrics**: MTTD 45min→5min | 2 N+1 bugs found | 5 custom dashboards | 7-day trace retention

---

### 7. Blue/Green Deployment with Terraform and Automated Rollback
**Architected IaC with Terraform (ECS Fargate, RDS, ElastiCache, ALB) and GitHub Actions Blue/Green workflow: deploy inactive color → smoke tests (health, query, eval) → ALB weight switch → 10min monitoring → auto-rollback on anomaly — achieving zero-downtime deploys, 2min rollback, 99.9% availability.**

**Technical Details**: Terraform modules (VPC, RDS pgvector, ElastiCache, ECS, ALB, Secrets Manager); Blue/Green via ALB target group weights; GitHub Actions workflow; smoke tests (health, sample query, eval thresholds); CloudWatch alarms for auto-rollback; AWS Secrets Manager rotation.

**Metrics**: Zero-downtime | Rollback 30min→2min | 99.9% availability | Full IaC

---

## Tailored Variants by Role

### For ML Platform Engineer
- Focus on bullets 1, 2, 3, 5 (core ML infrastructure)
- Emphasize: evaluation framework, embedding abstraction, vector store optimization
- Keywords: RAG, embeddings, vector search, evaluation, CI/CD

### For Backend/Platform Engineer
- Focus on bullets 2, 4, 5, 6, 7 (systems, APIs, infrastructure)
- Emphasize: MCP, observability, deployment, multi-provider architecture
- Keywords: FastAPI, Celery, PostgreSQL, Terraform, OpenTelemetry

### For Staff/Principal Engineer
- Combine all 7 with emphasis on **architectural decisions** and **organizational impact**
- Frame as: "Designed and led platform serving 15+ engineers, enabling weekly deployments with quality gates"
- Highlight: Cross-functional collaboration, mentoring, incident response, cost optimization

### For AI/ML Product Roles
- Focus on bullets 1, 3, 4 (user-facing quality, evaluation, developer experience)
- Emphasize: MRR improvement, evaluation rigor, MCP adoption
- Frame in terms of: User impact, iteration speed, quality assurance

---

## One-Liner Summary (for top of resume)

> **ContextForge**: Production RAG platform with multi-strategy chunking, 4 embedding providers, pgvector/FAISS/Weaviate, comprehensive evaluation (MRR@10=0.68), MCP for IDE integration, full observability, Blue/Green deployment — **40% retrieval improvement, 10x faster search, zero-downtime deploys**.

---

## Skills Keywords (for ATS)

**ML/RAG**: RAG, embeddings, vector search, chunking, retrieval evaluation, RAGAS, LLM-as-Judge, pgvector, FAISS, HNSW, hybrid search, BM25, reciprocal rank fusion

**Engineering**: FastAPI, Celery, PostgreSQL, SQLAlchemy, asyncio, Docker, Terraform, ECS Fargate, GitHub Actions, OpenTelemetry, Prometheus, Grafana, Tempo, Redis, MCP

**Practices**: CI/CD, Blue/Green deployment, IaC, secrets rotation, capacity planning, incident response, blameless postmortems, code review, mentoring