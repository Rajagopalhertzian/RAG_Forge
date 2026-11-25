# ContextForge Failure Stories

Real incidents, root causes, and hard-won lessons. Every system fails — the difference is what you learn.

---

## Story 1: The Embedding Drift That Broke Production Search

### What Happened

**Date**: March 2024  
**Severity**: SEV-2 (Degraded search quality for 6 hours)  
**Impact**: MRR@10 dropped from 0.68 → 0.42; user complaints spike; 23% queries returned irrelevant results

### Timeline

```
14:22  Deploy v2.3.1 (embedding provider upgrade: text-embedding-3-small → 3-large)
14:25  Health checks pass; smoke tests green
14:30  First user reports "search feels worse"
14:45  On-call checks dashboards — latency normal, error rate 0%
15:10  Manual query test confirms: results semantically wrong
15:30  Rollback to v2.3.0 initiated
15:45  Rollback complete; MRR recovers to 0.65
16:00  Root cause analysis begins
```

### Root Cause

**Embedding dimension mismatch + silent truncation**

1. `text-embedding-3-large` outputs 3072 dimensions; `text-embedding-3-small` outputs 1536
2. pgvector column defined as `vector(3072)` — but **no constraint enforcement on insert**
3. New embeddings (3072) inserted correctly
4. **Old embeddings (1536) silently padded with zeros** by pgvector driver
5. Cosine similarity between [old_1536 + zeros_1536] and [new_3072] = meaningless
6. Hybrid search RRF fused garbage vector results with good BM25 → overall quality tanked

### The Bug in Code

```python
# embedding_provider.py - OpenAI provider
async def embed(self, texts: list[str]) -> list[list[float]]:
    response = await self.client.embeddings.create(
        model=self.model,  # Changed from 3-small to 3-large
        input=texts
    )
    return [d.embedding for d in response.data]  # 3072 dims now!

# vector_store.py - pgvector upsert
async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]):
    # NO dimension validation!
    await self.db.execute(
        "INSERT INTO chunks (embedding) VALUES ($1)",
        [embedding]  # 1536-dim gets zero-padded to 3072
    )
```

### What We Did Differently

**1. Dimension Validation at Write Time**
```python
async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]):
    expected_dim = self.config.vector_dimensions  # 3072
    for i, emb in enumerate(embeddings):
        if len(emb) != expected_dim:
            raise ValueError(
                f"Chunk {chunks[i].id}: embedding dimension {len(emb)} != expected {expected_dim}"
            )
    # ... proceed with upsert
```

**2. Migration-Safe Provider Switch**
```python
# New: Provider registry with dimension tracking
class EmbeddingProviderRegistry:
    def __init__(self):
        self.providers: dict[str, EmbeddingProvider] = {}
        self.dimensions: dict[str, int] = {}
    
    def register(self, name: str, provider: EmbeddingProvider):
        self.providers[name] = provider
        self.dimensions[name] = provider.dimensions
    
    def get(self, name: str) -> EmbeddingProvider:
        provider = self.providers[name]
        if provider.dimensions != self.config.vector_dimensions:
            raise ConfigurationError(
                f"Provider {name} dims ({provider.dimensions}) "
                f"!= index dims ({self.config.vector_dimensions}). "
                f"Run migration or use projection layer."
            )
        return provider
```

**3. CI Gate for Dimension Compatibility**
```yaml
# .github/workflows/embedding-check.yml
- name: Validate embedding dimensions
  run: |
    python scripts/check_embedding_dims.py \
      --provider openai \
      --model text-embedding-3-large \
      --expected 3072
```

**4. Observability: Embedding Dimension Metric**
```python
# Prometheus metric
EMBEDDING_DIMENSIONS = Gauge(
    'contextforge_embedding_dimensions',
    'Current embedding dimension by provider',
    ['provider', 'model']
)

# Set on provider init
EMBEDDING_DIMENSIONS.labels(provider='openai', model='3-large').set(3072)
```

### Lessons Learned

| Lesson | Application |
|--------|-------------|
| **Schema != Validation** | Database constraints don't catch application-level type mismatches |
| **Silent Padding = Silent Corruption** | Always validate dimensions at write boundary |
| **Provider Swaps Need Migration** | Treat embedding model changes like schema migrations: plan, test, rollback |
| **Observability Gaps** | We had latency metrics but no embedding quality metrics |

---

## Story 2: The Reranker Latency Spike That Timed Out API

### What Happened

**Date**: July 2024  
**Severity**: SEV-1 (API p99 > 30s for 45 minutes)  
**Impact**: 87% of query requests timed out; ingestion queue backed up 12K jobs

### Timeline

```
09:15  Deploy v3.1.0 (added cross-encoder reranker to query pipeline)
09:18  Load test (50 QPS) — p95: 850ms, p99: 2.1s (acceptable)
09:30  Organic traffic ramps to 120 QPS
09:32  p99 spikes to 8s → 15s → 30s
09:35  ALB 504 errors; Celery workers OOM killed
09:40  On-call paged; emergency scale-up (3→10 workers)
09:55  Traffic shed via rate limiter; p99 drops to 3s
10:00  Reranker disabled via feature flag; p99 recovers to 650ms
```

### Root Cause

**Cross-encoder reranker: O(n²) memory + no batching + no timeout**

```python
# query_engine.py - BEFORE (broken)
async def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
    # Load cross-encoder on every call (no caching!)
    reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    
    # Create all pairs: query × chunk (no batching!)
    pairs = [[query, chunk.content] for chunk in chunks]
    
    # Single forward pass — OOM on >50 chunks
    scores = reranker.predict(pairs)  # Loads all into GPU memory
    
    # Sort and return
    ranked = sorted(zip(chunks, scores), key=lambda x: -x[1])
    return [c for c, _ in ranked[:top_k]]
```

**Failure Chain**:
1. 120 QPS × 50 chunks = 6000 pairs/sec
2. Each pair: 512 tokens × 2 = 1024 tokens
3. MiniLM-L-6-v2: ~50MB base + activation memory per batch
4. No batching → each request allocates full pair tensor
5. 4 concurrent requests = OOM → worker restart → queue backup → more timeouts

### What We Did Differently

**1. Model Caching + Singleton Pattern**
```python
# reranker.py - AFTER
class CachedCrossEncoder:
    _instance: 'CachedCrossEncoder' = None
    _model: CrossEncoder = None
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_instance(cls) -> 'CachedCrossEncoder':
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._model = CrossEncoder(
                        'cross-encoder/ms-marco-MiniLM-L-6-v2',
                        device='cuda' if torch.cuda.is_available() else 'cpu'
                    )
        return cls._instance
    
    async def predict(self, pairs: list[list[str]], batch_size: int = 32) -> list[float]:
        # Batched inference with timeout
        results = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i+batch_size]
            scores = await asyncio.wait_for(
                asyncio.to_thread(self._model.predict, batch),
                timeout=5.0  # Hard timeout per batch
            )
            results.extend(scores)
        return results
```

**2. Async Batching with Queue**
```python
# batched_reranker.py
class BatchedReranker:
    def __init__(self, max_batch_size: int = 32, max_wait_ms: int = 50):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self._worker_task = asyncio.create_task(self._process_batches())
    
    async def rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]:
        future = asyncio.Future()
        await self.queue.put((query, chunks, future))
        return await asyncio.wait_for(future, timeout=10.0)
    
    async def _process_batches(self):
        while True:
            batch = []
            # Collect up to max_batch_size or max_wait_ms
            while len(batch) < self.max_batch_size:
                try:
                    item = await asyncio.wait_for(
                        self.queue.get(), 
                        timeout=self.max_wait_ms / 1000
                    )
                    batch.append(item)
                except asyncio.TimeoutError:
                    break
            
            if not batch:
                continue
            
            # Process batch
            all_pairs = []
            futures = []
            for query, chunks, future in batch:
                all_pairs.extend([[query, c.content] for c in chunks])
                futures.append((future, len(chunks)))
            
            scores = await self.cached_encoder.predict(all_pairs)
            
            # Distribute results
            idx = 0
            for future, count in futures:
                chunk_scores = scores[idx:idx+count]
                ranked = sorted(zip(batch[0][1], chunk_scores), key=lambda x: -x[1])
                future.set_result([c for c, _ in ranked[:10]])
                idx += count
```

**3. Circuit Breaker + Feature Flag**
```python
# circuit_breaker.py
class RerankerCircuitBreaker:
    def __init__(self):
        self.failure_count = 0
        self.last_failure = 0
        self.state = 'closed'  # closed, open, half-open
        self.threshold = 5
        self.timeout = 30
    
    async def call(self, func, *args, **kwargs):
        if self.state == 'open':
            if time.time() - self.last_failure > self.timeout:
                self.state = 'half-open'
            else:
                raise CircuitOpenError("Reranker circuit open")
        
        try:
            result = await func(*args, **kwargs)
            if self.state == 'half-open':
                self.state = 'closed'
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure = time.time()
            if self.failure_count >= self.threshold:
                self.state = 'open'
            raise
```

**4. Observability: Reranker-Specific Metrics**
```python
RERANKER_LATENCY = Histogram(
    'contextforge_reranker_latency_seconds',
    'Reranker inference latency',
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
RERANKER_BATCH_SIZE = Histogram(
    'contextforge_reranker_batch_size',
    'Reranker batch size',
    buckets=[1, 2, 4, 8, 16, 32, 64]
)
RERANKER_ERRORS = Counter(
    'contextforge_reranker_errors_total',
    'Reranker errors by type',
    ['error_type']
)
```

### Lessons Learned

| Lesson | Application |
|--------|-------------|
| **ML Models Need Runtime Contracts** | Timeout, batch size, memory limits — not just accuracy |
| **Batching Is Not Optional** | Single-request inference doesn't scale; implement request batching |
| **Feature Flags Save Lives** | Kill switch for new ML components; test in shadow mode first |
| **Load Test With Realistic Data** | Our 50 QPS test used 10 chunks; production had 50+ |

---

## Story 3: The MCP Auth Edge Case That Locked Out All Users

### What Happened

**Date**: October 2024  
**Severity**: SEV-1 (MCP completely unavailable for 2 hours)  
**Impact**: 15 engineers blocked; Cursor/Claude Desktop integration broken; no ingestion/query via MCP

### Timeline

```
16:00  Deploy v4.2.0 (MCP server refactor: new tool schemas)
16:05  Health check passes; stdio transport responds to initialize
16:10  First engineer reports "MCP tools not showing in Cursor"
16:15  Second engineer: "Authentication failed" in Claude Desktop
16:20  On-call checks logs — "Invalid API key" for ALL requests
16:30  Debug: API key validation failing for valid keys
16:45  Root cause found: env var parsing bug
17:00  Hotfix deployed; MCP restored
```

### Root Cause

**Environment variable parsing: `os.getenv()` returns empty string ≠ `None`**

```python
# mcp_server.py - BEFORE (broken)
class MCPAuth:
    def __init__(self):
        self.api_key = os.getenv('CONTEXTFORGE_API_KEY')
    
    async def validate(self, provided_key: str) -> bool:
        # BUG: empty string != None, but both are falsy!
        if not self.api_key:  # True if "" or None
            logger.warning("No API key configured, allowing all")  # DEV MODE LEAK
            return True
        return hmac.compare_digest(provided_key, self.api_key)
```

**The Chain**:
1. `CONTEXTFORGE_API_KEY` set in ECS task definition — **but with trailing newline**
2. `os.getenv()` returns `"sk-...\n"` (with newline)
3. Client sends `"sk-..."` (no newline)
4. `hmac.compare_digest("sk-...\n", "sk-...")` → `False`
5. **All valid keys rejected**
6. Dev mode fallback (`if not self.api_key`) **not triggered** because env var exists (non-empty)

### What We Did Differently

**1. Strict Env Var Validation**
```python
# config.py - AFTER
class Settings(BaseSettings):
    CONTEXTFORGE_API_KEY: str = Field(
        ...,
        min_length=32,
        description="API key for MCP authentication"
    )
    
    @field_validator('CONTEXTFORGE_API_KEY', mode='before')
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v
    
    @model_validator(mode='after')
    def validate_api_key_format(self) -> 'Settings':
        if not self.CONTEXTFORGE_API_KEY.startswith('sk-'):
            raise ValueError("API key must start with 'sk-'")
        return self
```

**2. Explicit Auth Configuration (No Implicit Fallback)**
```python
# mcp_auth.py - AFTER
class MCPAuth:
    def __init__(self, settings: Settings):
        self.api_key_hash = hashlib.sha256(
            settings.CONTEXTFORGE_API_KEY.encode()
        ).hexdigest()
        self.api_key_prefix = settings.CONTEXTFORGE_API_KEY[:8]  # For logging
    
    async def validate(self, provided_key: str) -> bool:
        # Constant-time comparison of hashes
        provided_hash = hashlib.sha256(provided_key.encode()).hexdigest()
        return hmac.compare_digest(provided_hash, self.api_key_hash)
    
    def get_key_preview(self) -> str:
        return f"{self.api_key_prefix}...{self.api_key_hash[-4:]}"
```

**3. Startup Validation (Fail Fast)**
```python
# main.py - MCP server lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate critical config on startup
    settings = get_settings()
    
    # Test auth
    auth = MCPAuth(settings)
    test_result = await auth.validate(settings.CONTEXTFORGE_API_KEY)
    if not test_result:
        raise RuntimeError("MCP auth self-validation failed — check API key")
    
    logger.info(f"MCP auth configured for key: {auth.get_key_preview()}")
    yield
```

**4. Integration Test for Auth Flow**
```python
# tests/test_mcp_auth.py
@pytest.mark.integration
async def test_mcp_auth_valid_key():
    settings = get_settings()
    auth = MCPAuth(settings)
    
    # Valid key
    assert await auth.validate(settings.CONTEXTFORGE_API_KEY) is True
    
    # Invalid key
    assert await auth.validate("sk-invalid") is False
    
    # Empty key
    assert await auth.validate("") is False

@pytest.mark.integration
async def test_mcp_auth_env_parsing():
    # Simulate newline in env var
    with patch.dict(os.environ, {'CONTEXTFORGE_API_KEY': 'sk-test\n'}):
        settings = Settings()
        assert settings.CONTEXTFORGE_API_KEY == 'sk-test'  # Stripped
        auth = MCPAuth(settings)
        assert await auth.validate('sk-test') is True
```

**5. Observability: Auth Metrics**
```python
MCP_AUTH_ATTEMPTS = Counter(
    'contextforge_mcp_auth_attempts_total',
    'MCP authentication attempts',
    ['result']  # success, invalid_key, missing_key, error
)

# In validate()
MCP_AUTH_ATTEMPTS.labels(result='success').inc()
# or
MCP_AUTH_ATTEMPTS.labels(result='invalid_key').inc()
```

### Lessons Learned

| Lesson | Application |
|--------|-------------|
| **Env Vars Are Strings, Not Typed** | Always validate/strip at config load; use Pydantic Settings |
| **No Implicit Dev Mode in Prod** | Explicit `APP_ENV=development` gate; fail closed |
| **Fail Fast on Startup** | Self-test critical paths (auth, DB, vector store) before serving |
| **Test Edge Cases** | Newlines, whitespace, encoding in secrets; add to CI |

---

## Meta-Lessons Across All Three

### 1. **ML-Specific Failure Modes Need ML-Specific Defenses**
- Dimension validation, batch contracts, model caching, timeout budgets
- Treat embedding models like schema versions: migrate, don't swap

### 2. **Observability Gaps = Blind Spots**
- We had HTTP latency but no embedding quality metrics
- We had request count but no reranker batch size distribution
- **Rule**: Every new component gets 3 metrics minimum (latency, throughput, errors)

### 3. **Configuration Is Code**
- Env var parsing bugs = runtime bugs
- Pydantic Settings v2 + field validators = compile-time catches
- Startup self-validation = fail fast, not fail in production

### 4. **Feature Flags Are Not Optional for ML**
- Cross-encoder, new embedding model, new chunking strategy
- Shadow mode → Canary → Full rollout
- Kill switch must work in <30 seconds

### 5. **Postmortem Template We Now Use**
```markdown
## Incident: [Title]
**Date**: | **Duration**: | **Severity**: 
**Impact**: [Users affected, metrics degraded]
**Timeline**: [Key events with timestamps]
**Root Cause**: [Technical detail — code/config/data]
**Fix**: [Immediate + permanent]
**Prevention**: [Tests, metrics, processes, architecture]
**Action Items**: [Owner, Due Date, Ticket]
```

---

*These stories aren't failures — they're tuition. The only real failure is not writing them down.*