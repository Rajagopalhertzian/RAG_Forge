"""
ContextForge - Enterprise RAG Pipeline with Multi-Strategy Chunking & Embedding

A production-ready RAG (Retrieval-Augmented Generation) pipeline featuring:
- Multiple document loaders (PDF, Markdown, Notion, Confluence, GitHub, Slack)
- 4 chunking strategies (Semantic, Hierarchical, Code-aware, Fixed)
- 3 embedding backends (OpenAI, AWS Bedrock, Local sentence-transformers)
- Multiple vector stores (pgvector HNSW, FAISS, Weaviate)
- Async throughout with FastAPI, SQLAlchemy async, Celery
- Comprehensive evaluation framework
"""

__version__ = "0.1.0"
__author__ = "ContextForge Team"
__email__ = "team@contextforge.dev"

# Main exports
from contextforge.config import get_settings, settings
from contextforge.ingestion import (
    ChunkerRegistry,
    EmbedderRegistry,
    IndexerRegistry,
    IngestionPipeline,
    IngestionResult,
    LoaderRegistry,
)
from contextforge.main import app
from contextforge.storage import (
    Chunk,
    Document,
    EvalRun,
    Feedback,
    IngestionJob,
    QueryLog,
    close_db,
    get_session,
    init_db,
)

__all__ = [
    # Config
    "settings",
    "get_settings",
    # App
    "app",
    # Storage
    "Document",
    "Chunk",
    "IngestionJob",
    "QueryLog",
    "Feedback",
    "EvalRun",
    "init_db",
    "close_db",
    "get_session",
    # Ingestion
    "IngestionPipeline",
    "IngestionResult",
    "LoaderRegistry",
    "ChunkerRegistry",
    "EmbedderRegistry",
    "IndexerRegistry",
]
