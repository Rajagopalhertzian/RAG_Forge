"""
ContextForge pgvector Indexer

pgvector with HNSW index for PostgreSQL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector

from contextforge.config import settings
from contextforge.ingestion.indexers.base import (
    BaseIndexer,
    IndexerConfig,
    IndexerRegistry,
    VectorRecord,
)


class PgVectorIndexerConfig(IndexerConfig):
    """Configuration for pgvector indexer."""

    database_url: str = ""
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40
    table_name: str = "chunks"
    embedding_column: str = "embedding"


@IndexerRegistry.register
class PgVectorIndexer(BaseIndexer):
    """pgvector indexer using HNSW index."""

    indexer_name = "pgvector"

    def __init__(self, config: PgVectorIndexerConfig | None = None):
        config = config or PgVectorIndexerConfig()

        # Set defaults from settings
        if not config.database_url:
            config.database_url = str(settings.DATABASE_URL)
        if not config.dimensions:
            config.dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS
        if not config.hnsw_m:
            config.hnsw_m = settings.PGVECTOR_HNSW_M
        if not config.hnsw_ef_construction:
            config.hnsw_ef_construction = settings.PGVECTOR_HNSW_EF_CONSTRUCTION
        if not config.hnsw_ef_search:
            config.hnsw_ef_search = settings.PGVECTOR_HNSW_EF_SEARCH

        super().__init__(config)

        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Initialize connection pool and register vector type."""
        # Convert asyncpg URL to sync for pool
        url = self.config.database_url
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://")

        self._pool = await asyncpg.create_pool(
            url,
            min_size=5,
            max_size=20,
            init=self._init_connection,
        )

        # Ensure HNSW index exists
        await self._ensure_hnsw_index()

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """Initialize connection with vector type."""
        await register_vector(conn)

    async def _ensure_hnsw_index(self) -> None:
        """Create HNSW index if it doesn't exist."""
        async with self._pool.acquire() as conn:
            # Check if index exists
            index_exists = await conn.fetchval("""
                SELECT 1 FROM pg_indexes
                WHERE tablename = $1 AND indexname = $2
            """, self.config.table_name, f"{self.config.table_name}_{self.config.embedding_column}_hnsw")

            if not index_exists:
                await conn.execute(f"""
                    CREATE INDEX ON {self.config.table_name}
                    USING hnsw ({self.config.embedding_column} vector_cosine_ops)
                    WITH (m = {self.config.hnsw_m}, ef_construction = {self.config.hnsw_ef_construction})
                """)

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def upsert(self, records: list[VectorRecord]) -> int:
        """Insert or update vectors."""
        if not records:
            return 0

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for record in records:
                    await conn.execute(f"""
                        INSERT INTO {self.config.table_name} (id, {self.config.embedding_column}, metadata, document_id, chunk_index)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (id) DO UPDATE SET
                            {self.config.embedding_column} = EXCLUDED.{self.config.embedding_column},
                            metadata = EXCLUDED.metadata,
                            document_id = EXCLUDED.document_id,
                            chunk_index = EXCLUDED.chunk_index
                    """,
                        record.id,
                        record.embedding,
                        record.metadata,
                        record.document_id,
                        record.chunk_index,
                    )

        return len(records)

    async def delete(self, ids: list[UUID]) -> int:
        """Delete vectors by IDs."""
        if not ids:
            return 0

        async with self._pool.acquire() as conn:
            result = await conn.execute(f"""
                DELETE FROM {self.config.table_name}
                WHERE id = ANY($1)
            """, ids)

            # Extract count from result string "DELETE N"
            return int(result.split()[-1]) if result else 0

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        """Search for similar vectors using HNSW."""
        async with self._pool.acquire() as conn:
            # Set HNSW ef_search for this query
            await conn.execute(f"SET hnsw.ef_search = {self.config.hnsw_ef_search}")

            # Build query
            query = f"""
                SELECT id, {self.config.embedding_column}, metadata, document_id, chunk_index,
                       1 - ({self.config.embedding_column} <=> $1) AS similarity
                FROM {self.config.table_name}
                WHERE {self.config.embedding_column} IS NOT NULL
            """

            params = [query_embedding]
            param_idx = 2

            # Add metadata filters
            if filter_metadata:
                for key, value in filter_metadata.items():
                    query += f" AND metadata->>{key} = ${param_idx}"
                    params.append(str(value))
                    param_idx += 1

            query += f" ORDER BY similarity DESC LIMIT ${param_idx}"
            params.append(top_k)

            rows = await conn.fetch(query, *params)

            results = []
            for row in rows:
                record = VectorRecord(
                    id=row["id"],
                    embedding=row[self.config.embedding_column],
                    metadata=row["metadata"],
                    document_id=row["document_id"],
                    chunk_index=row["chunk_index"],
                )
                results.append((record, row["similarity"]))

            return results

    async def get_stats(self) -> dict[str, Any]:
        """Get indexer statistics."""
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM {self.config.table_name}")
            with_embedding = await conn.fetchval(f"""
                SELECT COUNT(*) FROM {self.config.table_name}
                WHERE {self.config.embedding_column} IS NOT NULL
            """)

            # Get index size
            index_size = await conn.fetchval("""
                SELECT pg_size_pretty(pg_relation_size($1))
            """, f"{self.config.table_name}_{self.config.embedding_column}_hnsw")

            return {
                "total_vectors": total,
                "vectors_with_embedding": with_embedding,
                "index_size": index_size,
                "dimensions": self.config.dimensions,
                "hnsw_m": self.config.hnsw_m,
                "hnsw_ef_construction": self.config.hnsw_ef_construction,
                "hnsw_ef_search": self.config.hnsw_ef_search,
            }
