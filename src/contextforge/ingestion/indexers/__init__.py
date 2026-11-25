"""
ContextForge Indexers Package

Vector indexers for similarity search.
"""

from contextforge.ingestion.indexers.base import (
    BaseIndexer,
    IndexerConfig,
    IndexerRegistry,
    VectorRecord,
)
from contextforge.ingestion.indexers.faiss import FaissIndexer, FaissIndexerConfig
from contextforge.ingestion.indexers.pgvector import PgVectorIndexer, PgVectorIndexerConfig
from contextforge.ingestion.indexers.weaviate import WeaviateIndexer, WeaviateIndexerConfig

__all__ = [
    "BaseIndexer",
    "IndexerConfig",
    "IndexerRegistry",
    "VectorRecord",
    "PgVectorIndexer",
    "PgVectorIndexerConfig",
    "FaissIndexer",
    "FaissIndexerConfig",
    "WeaviateIndexer",
    "WeaviateIndexerConfig",
]
