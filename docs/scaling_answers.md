# Scaling ContextForge: 10M Documents / 1,000 QPS

Architecture evolution from current (1M docs, 100 QPS) to 10M docs, 1,000 QPS.

---

## Scale Targets

| Metric | Current (Phase 1) | Target (Phase 2) | 10x Target (Phase 3) |
|--------|-------------------|------------------|----------------------|
| Documents | 1M | 10M | 100M+ |
| Chunks | 10M | 100M | 1B+ |
| Vector Dims | 3072 | 3072 | 3072 (or 1024 quantized) |
| QPS | 100 | 1,000 | 10,000 |
| p95 Latency | 650ms | <800ms | <500ms |
| Ingestion | 100 docs/min | 1,000 docs/min | 10,000 docs/min |
| Availability | 99.9% | 99.95% | 99.99% |

---

## Architecture Changes by Layer

### 1. Vector Store: pgvector → Sharded pgvector + Tiered Storage

**Current**: Single RDS instance, HNSW on all vectors

**Phase 2 (10M docs / 100M chunks)**:
```yaml
# Partitioning Strategy
Partitions:
  - By tenant/namespace (multi-tenancy ready)
  - By time: monthly partitions (rolling window)
  - By source_type: code, docs, slack, etc.

pgvector Setup:
  - Primary: Writes + recent partition (last 3 months) HNSW
  - Read Replicas: 3x for query distribution
  - Partition Pruning: WHERE source_type='code' AND created_at > '2024-01-01'

HNSW Tuning:
  - Recent partition: M=16, ef_construction=64, ef_search=40
  - Archive partitions: M=8, ef_construction=32 (smaller, slower build OK)
```

**Phase 3 (100M+ docs)**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Query Router                              │
│  (Metadata → Partition → Shard)                             │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  Hot Shard    │     │  Warm Shard   │     │  Cold Shard   │
│  (SSD, HNSW)  │     │  (HDD, IVF)   │     │  (S3, DiskANN)│
│  Last 30 days │     │  30d-2yr      │     │  2yr+         │
│  10M vectors  │     │  50M vectors  │     │  400M vectors │
└───────────────┘     └───────────────┘     └───────────────┘

Tiered Storage:
- Hot: pgvector HNSW on r6gd (NVMe) — p95 < 10ms
- Warm: pgvector IVFFlat on r6g (EBS) — p95 < 50ms  
- Cold: DiskANN on S3 Express One Zone — p95 < 200ms
```

**Migration Path**:
1. Add partitioned table (zero-downtime, dual-write)
2. Backfill partitions via async job
3. Switch query router to partition-aware
4. Archive old data to cold tier

### 2. Embedding Pipeline: Sync → Async Kafka + Distributed Workers

**Current**: Celery workers, in-process embedding, 100 docs/min

**Phase 2**:
```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Ingestion │────▶│    Kafka    │────▶│ Embedding Workers │
│   API       │     │  (buffer)   │     │  (Ray/Spark)      │
└─────────────┘     └─────────────┘     └────────┬─────────┘
                                                  │
                    ┌─────────────────────────────┘
                    ▼
           ┌──────────────────┐
           │  Vector Store    │
           │  (batched upsert)│
           └──────────────────┘
```

**Key Changes**:
- **Kafka Buffer**: Decouples ingestion API from embedding throughput
- **Ray Workers**: Horizontal scaling, GPU utilization, fault tolerance
- **Batch Embedding**: 512 texts/batch (vs 32), async HTTP/2
- **Exactly-Once**: Transactional outbox + Kafka idempotent producer

**Phase 3**:
- **Model Parallelism**: Split embedding model across GPUs (DeepSpeed)
- **Quantization**: INT8 embeddings (4x throughput, <1% recall loss)
- **Caching**: Redis cache for repeated content (deduplication)

### 3. Query Engine: Single-Node → Distributed Two-Stage

**Current**: Single API → pgvector HNSW → RRF → return

**Phase 2**: Two-Stage Retrieval
```
Query → Rewrite/Expand → Stage 1: Coarse Retrieval (IVF, top 200)
                          → Stage 2: Fine Rerank (HNSW + Cross-Encoder, top 20)
                          → RRF Fusion → Return
```

**Phase 3**: Sharded Query Fanout
```
Query → Router → Parallel Shard Queries → Merge (RRF) → Rerank → Return
        │
        ├─▶ Shard 1 (tenant A) ──▶ IVF → HNSW → top 50
        ├─▶ Shard 2 (tenant B) ──▶ IVF → HNSW → top 50
        └─▶ Shard N ...          ──▶ ...
```

**Optimizations**:
- **Query Embedding Cache**: Redis TTL 1hr for repeated queries (~30% cache hit)
- **Result Cache**: Full query result cache for popular queries
- **Async Pipeline**: Rewrite → Retrieve → Rerank in parallel stages

### 4. Ingestion: Celery → Kafka + Ray + Exactly-Once

**Current**: Celery + Redis, at-least-once, 100 docs/min

**Phase 2**:
```python
# Exactly-Once Ingestion Flow
async def ingest_document(document: Document) -> IngestionJob:
    # 1. Idempotency key (content hash)
    content_hash = sha256(document.content)
    existing = await db.documents.find_by_hash(content_hash)
    if existing:
        return IngestionJob(document_id=existing.id, status='duplicate')
    
    # 2. Transactional outbox
    async with db.transaction():
        job = await db.ingestion_jobs.create(
            document_id=document.id,
            content_hash=content_hash,
            status='pending'
        )
        await db.outbox.insert(
            event_type='ingest',
            payload={'job_id': job.id, 'document': document.dict()}
        )
    
    # 3. Kafka producer (idempotent)
    await kafka.producer.send(
        'ingestion.jobs',
        key=job.id,
        value=job.dict(),
        enable_idempotence=True
    )
    return job

# Consumer (Ray actor)
@ray.remote
class IngestionWorker:
    async def process(self, job: IngestionJob):
        # Deduplication via Redis SET
        processed = await redis.setnx(f"ingested:{job.content_hash}", "1", ex=86400)
        if not processed:
            return  # Already processed
        
        # Chunk → Embed → Store (batched)
        chunks = self.chunker.chunk(job.document.content)
        embeddings = await self.embedder.embed_batch(chunks, batch_size=512)
        await self.vector_store.upsert_batch(chunks, embeddings)
        
        await db.ingestion_jobs.update(job.id, status='completed')
```

### 5. API Layer: Horizontal Scaling + Smart Routing

**Current**: 4 Fargate tasks, ALB round-robin

**Phase 2**:
- **Auto-scaling**: CPU > 70% → +2 tasks (max 20)
- **Request Affinity**: Session stickiness for WebSocket (future)
- **Rate Limiting**: Distributed token bucket (Redis Cluster)
- **Circuit Breakers**: Per downstream (vector store, embedding API)

**Phase 3**:
```
┌─────────────────────────────────────────────────────────────┐
│                      API Gateway (Kong/Envoy)                │
│  Rate Limit │ Auth │ Routing │ Observability │ Cache        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  Query API    │     │  Ingestion    │     │  Eval API     │
│  (Read Heavy) │     │  (Write Heavy)│     │  (Batch)      │
│  15 replicas  │     │  10 replicas  │     │  3 replicas   │
└───────────────┘     └───────────────┘     └───────────────┘
```

### 6. Observability: Sampling + Aggregation

**Current**: 100% traces, full metrics

**Phase 2**: Tail-Based Sampling (10%)
```yaml
# otel-collector config
processors:
  tail_sampling:
    decision_wait: 30s
    num_traces: 50000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors-only
        type: string_attribute
        string_attribute:
          key: "error"
          values: ["true"]
      - name: slow-traces
        type: latency
        latency:
          threshold_ms: 1000
      - name: probabilistic
        type: probabilistic
        probabilistic:
          sampling_percentage: 10
```

**Phase 3**: Metric Aggregation + Exemplars
- **Pre-aggregate** in application (OpenTelemetry Views)
- **Exemplars**: Link metrics to traces for p99 investigation
- **Cardinality Limits**: Max 1000 label combinations per metric

### 7. Database: Read Replicas + Connection Pooling

**Current**: Single RDS primary, asyncpg pool (20 connections)

**Phase 2**:
```yaml
# PgBouncer Configuration
pool_mode: transaction
max_client_conn: 1000
default_pool_size: 100
min_pool_size: 20
reserve_pool_size: 10
reserve_pool_timeout: 5

# Read Replica Setup
Primary: Writes + Index Builds
Replica 1: Query API (vector search)
Replica 2: Query API (keyword search)
Replica 3: Analytics / Eval
```

**Phase 3**: 
- **RDS Proxy**: Connection multiplexing, failover <30s
- **Partitioned Tables**: Parallel query execution
- **Columnar Storage**: For analytics workloads (eval, reporting)

---

## Cost Model at Scale

| Component | Phase 1 (1M) | Phase 2 (10M) | Phase 3 (100M) |
|-----------|--------------|---------------|----------------|
| **Compute (API)** | $450/mo | $1,800/mo | $8,000/mo |
| **Compute (Workers)** | $600/mo | $3,000/mo | $15,000/mo |
| **RDS (pgvector)** | $800/mo | $2,500/mo | $12,000/mo |
| **ElastiCache** | $600/mo | $1,500/mo | $6,000/mo |
| **Kafka (MSK)** | - | $800/mo | $3,000/mo |
| **Ray/GPU Workers** | - | $2,000/mo | $20,000/mo |
| **S3/Storage** | $50/mo | $300/mo | $2,000/mo |
| **Data Transfer** | $450/mo | $2,000/mo | $15,000/mo |
| **Observability** | $200/mo | $800/mo | $3,000/mo |
| **Total/Month** | **~$3,150** | **~$14,700** | **~$84,000** |

**Cost Optimization at Scale**:
1. **Spot Instances**: 80% for workers (Ray, embedding)
2. **Quantization**: INT8 embeddings → 4x storage/compute savings
3. **Tiered Storage**: Hot/Warm/Cold → 70% storage cost reduction
4. **Sparse Embeddings**: SPLADE for keyword-heavy → 10x smaller
5. **RDS Instance Scheduling**: Dev environments off nights/weekends

---

## Capacity Planning Formulas

### Vector Store Sizing
```
Raw Vectors = Documents × Chunks/Doc × Dimensions × 4 bytes
HNSW Overhead = Raw Vectors × 1.4 (graph + metadata)
Index Build Time = Vectors × log(Vectors) × ef_construction / (CPU cores × parallelism)
Memory for HNSW = Vectors × M × 8 bytes (connections)
```

### Query Throughput
```
Max QPS = (Replicas × Cores/Replica) / (Latency_p95 × Safety_Factor)
# Example: 10 replicas × 4 cores / (0.05s × 2) = 400 QPS
# For 1000 QPS: Need 25 replicas or reduce p95 to 20ms
```

### Ingestion Throughput
```
Docs/Min = (Workers × Batch_Size × Embeddings_Per_Sec) / Chunks_Per_Doc
# Example: 20 workers × 512 batch × 100 emb/s / 10 chunks = 10,240 docs/min
```

---

## Migration Checklist: Phase 1 → Phase 2

### Infrastructure
- [ ] Provision RDS read replicas (3x)
- [ ] Set up PgBouncer connection pooling
- [ ] Deploy Kafka cluster (MSK 3-AZ)
- [ ] Deploy Ray cluster (GPU nodes for embedding)
- [ ] Configure Redis Cluster mode
- [ ] Set up API Gateway (Kong/Envoy)

### Application
- [ ] Implement partition-aware vector store adapter
- [ ] Add Kafka producer/consumer for ingestion
- [ ] Build Ray embedding actors
- [ ] Implement two-stage retrieval (IVF → HNSW)
- [ ] Add query embedding cache (Redis)
- [ ] Implement tail-based sampling for traces

### Data Migration
- [ ] Create partitioned tables (dual-write)
- [ ] Backfill partitions (async, checkpointed)
- [ ] Validate partition pruning works
- [ ] Switch query router to partition-aware
- [ ] Archive cold data to S3

### Operations
- [ ] Update runbooks for new components
- [ ] Add Kafka lag alerts
- [ ] Add Ray worker health checks
- [ ] Update capacity planning dashboards
- [ ] Load test at 2x target QPS

---

## Key Scaling Principles

1. **Partition by Access Pattern**: Tenant, time, source_type — not random hash
2. **Tier by Temperature**: Hot data on fast storage, cold on cheap
3. **Batch Everything**: Embedding, upsert, query — amortize fixed costs
4. **Cache at Every Layer**: Query embeddings, search results, generated answers
5. **Observe Before Scaling**: Metrics drive decisions, not guesses
6. **Fail Gracefully**: Circuit breakers, degradation modes, not hard failures
7. **Automate Capacity**: Autoscaling based on custom metrics (queue depth, p99)

---

*The architecture that works at 1M docs won't work at 100M. Plan the migration, not just the destination.*