"""
ContextForge Weaviate Indexer

Weaviate vector indexer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter, MetadataQuery

from contextforge.config import settings
from contextforge.ingestion.indexers.base import (
    BaseIndexer,
    IndexerConfig,
    IndexerRegistry,
    VectorRecord,
)


class WeaviateIndexerConfig(IndexerConfig):
    """Configuration for Weaviate indexer."""

    url: str = "http://localhost:8080"
    api_key: str | None = None
    class_prefix: str = "ContextForge"
    class_name: str = "Chunk"


@IndexerRegistry.register
class WeaviateIndexer(BaseIndexer):
    """Weaviate vector indexer."""

    indexer_name = "weaviate"

    def __init__(self, config: WeaviateIndexerConfig | None = None):
        config = config or WeaviateIndexerConfig()

        # Set defaults from settings
        if not config.url:
            config.url = str(settings.WEAVIATE_URL)
        if not config.api_key:
            config.api_key = settings.WEAVIATE_API_KEY
        if not config.class_prefix:
            config.class_prefix = settings.WEAVIATE_CLASS_PREFIX
        if not config.dimensions:
            config.dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS

        super().__init__(config)

        self._client: weaviate.WeaviateClient | None = None
        self._class_name = f"{config.class_prefix}{config.class_name}"

    async def initialize(self) -> None:
        """Initialize Weaviate client and schema."""
        self._client = weaviate.connect_to_custom(
            http_host=self.config.url.replace("http://", "").replace("https://", "").split(":")[0],
            http_port=int(self.config.url.split(":")[-1]) if ":" in self.config.url else 8080,
            http_secure=self.config.url.startswith("https"),
            auth_credentials=Auth.api_key(self.config.api_key) if self.config.api_key else None,
        )

        # Create class if not exists
        await self._ensure_schema()

    async def _ensure_schema(self) -> None:
        """Ensure the class schema exists."""
        if not self._client.collections.exists(self._class_name):
            self._client.collections.create(
                name=self._class_name,
                vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
                vector_index_config=weaviate.classes.config.Configure.VectorIndex.hnsw(
                    distance_metric=weaviate.classes.config.VectorDistances.COSINE,
                ),
                properties=[
                    weaviate.classes.config.Property(name="document_id", data_type=weaviate.classes.config.DataType.UUID),
                    weaviate.classes.config.Property(name="chunk_index", data_type=weaviate.classes.config.DataType.INT),
                    weaviate.classes.config.Property(name="metadata", data_type=weaviate.classes.config.DataType.OBJECT),
                    weaviate.classes.config.Property(name="content", data_type=weaviate.classes.config.DataType.TEXT),
                ],
            )

    async def close(self) -> None:
        """Close Weaviate client."""
        if self._client:
            self._client.close()
            self._client = None

    async def upsert(self, records: list[VectorRecord]) -> int:
        """Insert or update vectors."""
        if not records or not self._client:
            return 0

        collection = self._client.collections.get(self._class_name)

        with collection.batch.dynamic() as batch:
            for record in records:
                batch.add_object(
                    properties={
                        "document_id": str(record.document_id) if record.document_id else None,
                        "chunk_index": record.chunk_index,
                        "metadata": record.metadata,
                        "content": record.metadata.get("content", ""),
                    },
                    vector=record.embedding,
                    uuid=str(record.id),
                )

        return len(records)

    async def delete(self, ids: list[UUID]) -> int:
        """Delete vectors by IDs."""
        if not ids or not self._client:
            return 0

        collection = self._client.collections.get(self._class_name)

        # Weaviate doesn't have bulk delete by UUID list easily
        # Delete one by one
        deleted = 0
        for id in ids:
            try:
                collection.data.delete_by_id(str(id))
                deleted += 1
            except Exception:
                pass

        return deleted

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        """Search for similar vectors."""
        if not self._client:
            return []

        collection = self._client.collections.get(self._class_name)

        # Build filter
        filters = None
        if filter_metadata:
            filter_conditions = []
            for key, value in filter_metadata.items():
                filter_conditions.append(Filter.by_property(key).equal(value))
            if filter_conditions:
                filters = filter_conditions[0]
                for f in filter_conditions[1:]:
                    filters = filters & f

        # Search
        response = collection.query.near_vector(
            near_vector=query_embedding,
            limit=top_k,
            filters=filters,
            return_metadata=MetadataQuery(distance=True),
            return_properties=["document_id", "chunk_index", "metadata", "content"],
        )

        results = []
        for obj in response.objects:
            record = VectorRecord(
                id=UUID(obj.uuid),
                embedding=[],  # Not returned by default
                metadata=obj.properties.get("metadata", {}),
                document_id=UUID(obj.properties["document_id"]) if obj.properties.get("document_id") else None,
                chunk_index=obj.properties.get("chunk_index"),
            )
            # Distance is 0-2 for cosine, convert to similarity
            similarity = 1.0 - (obj.metadata.distance / 2.0) if obj.metadata.distance else 0.0
            results.append((record, similarity))

        return results

    async def get_stats(self) -> dict[str, Any]:
        """Get indexer statistics."""
        if not self._client:
            return {}

        collection = self._client.collections.get(self._class_name)
        count = collection.aggregate.over_all(total_count=True)

        return {
            "total_vectors": count.total_count,
            "dimensions": self.config.dimensions,
            "class_name": self._class_name,
            "url": self.config.url,
        }
