"""
ContextForge Ingestion Pipeline

Orchestrates the full ingestion process: load -> chunk -> embed -> index.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contextforge.config import settings
from contextforge.ingestion.chunkers.base import BaseChunker, ChunkerRegistry
from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderRegistry
from contextforge.ingestion.indexers.base import BaseIndexer, IndexerRegistry, VectorRecord
from contextforge.ingestion.loaders.base import BaseLoader, LoaderRegistry
from contextforge.storage.database import (
    get_session,
)
from contextforge.storage.repositories import (
    ChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of an ingestion operation."""

    document_id: UUID
    job_id: UUID
    chunk_count: int
    strategy: str
    embedding_provider: str
    embedding_model: str
    success: bool
    error_message: str | None = None


class IngestionPipeline:
    """Orchestrates the ingestion pipeline."""

    def __init__(
        self,
        loader: BaseLoader | None = None,
        chunker: BaseChunker | None = None,
        embedder: BaseEmbedder | None = None,
        indexer: BaseIndexer | None = None,
    ):
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.indexer = indexer

    @classmethod
    def from_config(
        cls,
        source_type: str,
        strategy: str | None = None,
        embedding_provider: str | None = None,
        vector_store: str | None = None,
        loader_config: dict[str, Any] | None = None,
        chunker_config: dict[str, Any] | None = None,
        embedder_config: dict[str, Any] | None = None,
        indexer_config: dict[str, Any] | None = None,
    ) -> IngestionPipeline:
        """Create pipeline from configuration."""
        # Get loader
        loader_class = LoaderRegistry.get(source_type)
        if not loader_class:
            raise ValueError(f"Unknown source type: {source_type}")
        loader = loader_class(**(loader_config or {}))

        # Get chunker
        strategy = strategy or settings.DEFAULT_CHUNK_STRATEGY
        chunker_class = ChunkerRegistry.get(strategy)
        if not chunker_class:
            raise ValueError(f"Unknown chunking strategy: {strategy}")
        chunker = chunker_class(**(chunker_config or {}))

        # Get embedder
        embedding_provider = embedding_provider or "local"
        embedder_class = EmbedderRegistry.get(embedding_provider)
        if not embedder_class:
            raise ValueError(f"Unknown embedding provider: {embedding_provider}")
        embedder = embedder_class(**(embedder_config or {}))

        # Get indexer
        vector_store = vector_store or settings.VECTOR_STORE
        indexer_class = IndexerRegistry.get(vector_store)
        if not indexer_class:
            raise ValueError(f"Unknown vector store: {vector_store}")
        indexer = indexer_class(**(indexer_config or {}))

        return cls(loader=loader, chunker=chunker, embedder=embedder, indexer=indexer)

    async def initialize(self) -> None:
        """Initialize all components."""
        if self.indexer:
            await self.indexer.initialize()

    async def close(self) -> None:
        """Close all components."""
        if self.indexer:
            await self.indexer.close()
        if self.loader and hasattr(self.loader, "close"):
            await self.loader.close()

    async def ingest(
        self,
        source_id: str,
        *,
        strategy: str | None = None,
        embedding_provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Ingest a single document."""
        job_id = uuid4()
        document_id = None

        async with get_session() as session:
            job_repo = IngestionJobRepository(session)
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            # Create job record
            job = await job_repo.create(
                id=job_id,
                source_type=self.loader.source_type if self.loader else "unknown",
                source_id=source_id,
                status="processing",
                strategy=strategy or self.chunker.strategy_name if self.chunker else "unknown",
                embedding_provider=embedding_provider or self.embedder.provider_name if self.embedder else "unknown",
                embedding_model=embedding_provider or self.embedder.model_name if self.embedder else "unknown",
                started_at=datetime.utcnow(),
                metadata=metadata or {},
            )

            try:
                # Load document
                logger.info(f"Loading document: {source_id}")
                doc_content = await self.loader.load(source_id)

                # Compute content hash
                content_hash = hashlib.sha256(doc_content.content.encode()).hexdigest()

                # Check for duplicate
                existing = await doc_repo.get_by_content_hash(content_hash)
                if existing:
                    logger.info(f"Document already exists: {existing.id}")
                    await job_repo.mark_completed(job_id, existing.id, existing.chunk_count)
                    return IngestionResult(
                        document_id=existing.id,
                        job_id=job_id,
                        chunk_count=existing.chunk_count,
                        strategy=strategy or self.chunker.strategy_name,
                        embedding_provider=embedding_provider or self.embedder.provider_name,
                        embedding_model=embedding_provider or self.embedder.model_name,
                        success=True,
                    )

                # Chunk document
                logger.info(f"Chunking document with strategy: {self.chunker.strategy_name}")
                chunks = self.chunker.chunk(doc_content.content, doc_content.metadata)

                # Generate embeddings
                logger.info(f"Generating embeddings with: {self.embedder.provider_name}/{self.embedder.model_name}")
                chunk_texts = [c.content for c in chunks]
                embeddings = self.embedder.embed_batch(chunk_texts)

                # Create document record
                document = await doc_repo.create(
                    source_type=self.loader.source_type,
                    source_id=source_id,
                    title=doc_content.title,
                    content=doc_content.content,
                    metadata=doc_content.metadata,
                    content_hash=content_hash,
                    chunk_count=len(chunks),
                )
                document_id = document.id

                # Create chunk records with embeddings
                vector_records = []
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_record = await chunk_repo.create(
                        document_id=document_id,
                        chunk_index=i,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        strategy=self.chunker.strategy_name,
                        metadata=chunk.metadata,
                        embedding=embedding,
                        embedding_model=self.embedder.model_name,
                        embedding_provider=self.embedder.provider_name,
                    )

                    # Prepare for vector index
                    vector_records.append(VectorRecord(
                        id=chunk_record.id,
                        embedding=embedding,
                        metadata={
                            **chunk.metadata,
                            "document_id": str(document_id),
                            "chunk_index": i,
                            "content": chunk.content[:1000],  # Truncate for metadata
                        },
                        document_id=document_id,
                        chunk_index=i,
                    ))

                # Index vectors
                logger.info(f"Indexing {len(vector_records)} vectors")
                if self.indexer:
                    await self.indexer.upsert(vector_records)

                # Mark job complete
                await job_repo.mark_completed(job_id, document_id, len(chunks))

                logger.info(f"Ingestion complete: {document_id} ({len(chunks)} chunks)")

                return IngestionResult(
                    document_id=document_id,
                    job_id=job_id,
                    chunk_count=len(chunks),
                    strategy=self.chunker.strategy_name,
                    embedding_provider=self.embedder.provider_name,
                    embedding_model=self.embedder.model_name,
                    success=True,
                )

            except Exception as e:
                logger.exception(f"Ingestion failed for {source_id}: {e}")
                await job_repo.mark_failed(job_id, str(e))

                return IngestionResult(
                    document_id=document_id or uuid4(),
                    job_id=job_id,
                    chunk_count=0,
                    strategy=strategy or self.chunker.strategy_name if self.chunker else "unknown",
                    embedding_provider=embedding_provider or self.embedder.provider_name if self.embedder else "unknown",
                    embedding_model=embedding_provider or self.embedder.model_name if self.embedder else "unknown",
                    success=False,
                    error_message=str(e),
                )

    async def ingest_batch(
        self,
        source_ids: list[str],
        *,
        strategy: str | None = None,
        embedding_provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestionResult]:
        """Ingest multiple documents."""
        results = []
        for source_id in source_ids:
            result = await self.ingest(
                source_id,
                strategy=strategy,
                embedding_provider=embedding_provider,
                metadata=metadata,
            )
            results.append(result)
        return results


class AsyncIngestionPipeline(IngestionPipeline):
    """Async version of ingestion pipeline using Celery."""

    async def ingest_async(
        self,
        source_id: str,
        *,
        strategy: str | None = None,
        embedding_provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Submit ingestion job to Celery queue."""
        from contextforge.workers.tasks import ingest_document_task

        job_id = uuid4()

        async with get_session() as session:
            job_repo = IngestionJobRepository(session)
            await job_repo.create(
                id=job_id,
                source_type=self.loader.source_type if self.loader else "unknown",
                source_id=source_id,
                status="pending",
                strategy=strategy or self.chunker.strategy_name if self.chunker else "unknown",
                embedding_provider=embedding_provider or self.embedder.provider_name if self.embedder else "unknown",
                embedding_model=embedding_provider or self.embedder.model_name if self.embedder else "unknown",
                metadata=metadata or {},
            )

        # Submit to Celery
        ingest_document_task.delay(
            str(job_id),
            source_id,
            strategy or self.chunker.strategy_name,
            embedding_provider or self.embedder.provider_name,
            metadata or {},
        )

        return job_id
