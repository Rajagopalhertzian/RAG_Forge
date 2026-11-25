# ContextForge

**Enterprise RAG Pipeline with Multi-Strategy Chunking & Embedding**

A production-ready Retrieval-Augmented Generation (RAG) pipeline featuring multiple document loaders, 4 chunking strategies, 3 embedding backends, and multiple vector stores.

## Features

### Document Ingestion
- **Loaders**: PDF, Markdown, Notion, Confluence, GitHub, Slack
- **Async throughout** with FastAPI, SQLAlchemy async, Celery

### Chunking Strategies (4)
1. **Semantic** - Embedding-based boundary detection with configurable threshold
2. **Hierarchical** - Parent-child chunks for multi-granularity retrieval
3. **Code-aware** - Tree-sitter AST-based chunking for source code
4. **Fixed** - Recursive character splitting with configurable separators

### Embedding Providers (3)
1. **OpenAI** - text-embedding-3-large (3072 dims) + Azure OpenAI support
2. **AWS Bedrock** - Titan v2, Cohere v3 (1024 dims)
3. **Local** - BGE-M3, E5 via sentence-transformers (1024 dims)

### Vector Stores (3)
1. **pgvector** - Primary: PostgreSQL with HNSW index
2. **FAISS** - Local development fallback
3. **Weaviate** - Optional distributed vector store

### Evaluation Framework
- **Chunking**: Boundary preservation score, semantic coherence
- **Embeddings**: Alignment (query-doc cosine), clustering (silhouette), retrieval proxy (MRR)
- **Golden set** generation for benchmarking

### Observability
- Structured JSON logging with request IDs
- Prometheus metrics (`/metrics`)
- OpenTelemetry tracing
- Redis-backed rate limiting (token bucket)

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 16+ with pgvector extension
- Redis 7+
- uv (recommended) or pip

### Installation

```bash
# Clone and enter directory
git clone <repo>
cd contextforge

# Install dependencies with uv
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Copy environment template
cp .env.example .env
# Edit .env with your configuration
```

### Database Setup

```bash
# Run migrations
uv run alembic upgrade head

# Or create new migration
uv run alembic revision --autogenerate -m "description"
```

### Running Locally

```bash
# Start API server
uv run uvicorn contextforge.main:app --reload

# Start Celery worker (in separate terminal)
uv run celery -A contextforge.workers.celery_app worker --loglevel=info

# Run ingestion CLI
python scripts/ingest_corpus.py ./docs/sample.pdf --source-type pdf
```

### Docker Deployment

```bash
# Build and start all services
docker compose -f docker/docker-compose.yml up -d

# With observability stack
docker compose -f docker/docker-compose.yml --profile with-observability up -d

# With Weaviate
docker compose -f docker/docker-compose.yml --profile with-weaviate up -d
```

## API Endpoints

### Ingestion
```
POST   /api/v1/ingestion/ingest          # Submit async ingestion job
POST   /api/v1/ingestion/ingest/sync     # Synchronous ingestion
POST   /api/v1/ingestion/ingest/file     # Upload and ingest file
POST   /api/v1/ingestion/ingest/batch    # Batch ingestion
GET    /api/v1/ingestion/ingest/status/{job_id}  # Check job status
GET    /api/v1/ingestion/strategies      # List chunking strategies
GET    /api/v1/ingestion/providers       # List embedding providers
GET    /api/v1/ingestion/sources         # List source types
GET    /api/v1/ingestion/indexers        # List vector indexers
```

### Health & Monitoring
```
GET    /health           # Health check
GET    /metrics          # Prometheus metrics
GET    /docs             # OpenAPI docs (dev only)
```

## Configuration

Key environment variables (see `.env.example`):

```bash
# Application
APP_ENV=development
APP_DEBUG=true

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/contextforge

# Redis
REDIS_URL=redis://localhost:6379/0

# Embeddings
OPENAI_API_KEY=sk-...
AWS_REGION=us-east-1
LOCAL_EMBEDDING_MODEL=BAAI/bge-m3

# Vector Store
VECTOR_STORE=pgvector  # or faiss, weaviate

# Chunking
DEFAULT_CHUNK_STRATEGY=semantic
DEFAULT_CHUNK_SIZE=512
```

## Project Structure

```
contextforge/
├── src/contextforge/
│   ├── config.py              # Pydantic Settings v2
│   ├── main.py                # FastAPI app + middleware
│   ├── api/routes/            # API endpoints
│   ├── ingestion/
│   │   ├── loaders/           # Document loaders
│   │   ├── chunkers/          # Chunking strategies
│   │   ├── embedders/         # Embedding providers
│   │   ├── indexers/          # Vector stores
│   │   └── pipeline.py        # Orchestration
│   ├── storage/
│   │   ├── database.py        # SQLAlchemy models
│   │   └── repositories/      # Data access layer
│   └── workers/               # Celery tasks
├── scripts/
│   └── ingest_corpus.py       # CLI for ingestion
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── docker-compose.yml
├── alembic/                   # Database migrations
├── tests/
│   ├── unit/                  # Unit tests
│   └── integration/           # Integration tests
└── .github/workflows/ci.yml   # CI pipeline
```

## Development

### Code Quality
```bash
# Format code
uv run ruff format src tests

# Lint
uv run ruff check src tests

# Type check
uv run mypy src

# Run all checks
make check
```

### Testing
```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit -v

# Integration tests
uv run pytest tests/integration -v

# With coverage
uv run pytest --cov=contextforge --cov-report=html
```

### Adding a New Chunker
1. Create `src/contextforge/ingestion/chunkers/new_chunker.py`
2. Inherit from `BaseChunker`
3. Implement `strategy_name` property and `chunk()` method
4. Register with `@ChunkerRegistry.register`
5. Add tests in `tests/unit/test_chunkers.py`

### Adding a New Loader
1. Create `src/contextforge/ingestion/loaders/new_loader.py`
2. Inherit from `BaseLoader`
3. Implement `source_type`, `load()`, `load_many()`, `validate_source()`
4. Register with `@LoaderRegistry.register`

## Evaluation

Run chunking evaluation:
```bash
python -m contextforge.ingestion.chunkers.evaluation
```

Run embedding evaluation:
```bash
python -m contextforge.ingestion.embedders.evaluation
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System diagram, data flows, component responsibilities |
| [API Reference](docs/api.md) | OpenAPI spec, endpoint docs, examples |
| [MCP Integration](docs/mcp_integration.md) | Connect Claude Desktop/Cursor, tool schemas |
| [Evaluation Guide](docs/evaluation_guide.md) | Golden sets, running evals, CI gates |
| [Deployment](docs/deployment.md) | Terraform, Blue/Green, rollback, scaling |
| [Interview Prep](docs/interview_prep.md) | STAR answers, Q&A for all SPEC topics |
| [Resume Bullets](docs/resume_bullets.md) | 7 tailored bullets from SPEC Section 11 |
| [Tradeoff Cards](docs/tradeoff_cards.md) | 15 architectural decisions with data-backed rationale |
| [Failure Stories](docs/failure_stories.md) | 3 real incidents: embedding drift, reranker latency, MCP auth |
| [Scaling Answers](docs/scaling_answers.md) | 10M docs / 1000 QPS architecture evolution |
| [Live Demo Script](docs/live_demo_script.md) | 3-min demo: ingest → query → trace → eval dashboard |

## License

MIT License - see LICENSE file for details.