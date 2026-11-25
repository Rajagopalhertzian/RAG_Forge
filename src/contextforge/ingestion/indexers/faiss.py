"""
ContextForge FAISS Indexer

FAISS index for local development.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any
from uuid import UUID

import faiss
import numpy as np

from contextforge.config import settings
from contextforge.ingestion.indexers.base import (
    BaseIndexer,
    IndexerConfig,
    IndexerRegistry,
    VectorRecord,
)


class FaissIndexerConfig(IndexerConfig):
    """Configuration for FAISS indexer."""

    index_path: str = "./data/faiss_index"
    index_type: str = "HNSW32"  # HNSW32, IVF100, Flat
    save_on_update: bool = True


@IndexerRegistry.register
class FaissIndexer(BaseIndexer):
    """FAISS indexer for local development."""

    indexer_name = "faiss"

    def __init__(self, config: FaissIndexerConfig | None = None):
        config = config or FaissIndexerConfig()

        # Set defaults from settings
        if not config.index_path:
            config.index_path = settings.FAISS_INDEX_PATH
        if not config.index_type:
            config.index_type = settings.FAISS_INDEX_TYPE
        if not config.dimensions:
            config.dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS

        super().__init__(config)

        self._index: faiss.Index | None = None
        self._id_to_idx: dict[UUID, int] = {}
        self._idx_to_record: dict[int, VectorRecord] = {}
        self._next_idx: int = 0
        self._index_path = Path(config.index_path)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)

    def _create_index(self) -> faiss.Index:
        """Create FAISS index based on type."""
        dim = self.config.dimensions
        index_type = self.config.index_type.upper()

        if index_type == "FLAT":
            return faiss.IndexFlatIP(dim)
        elif index_type.startswith("IVF"):
            nlist = int(index_type[3:]) if len(index_type) > 3 else 100
            quantizer = faiss.IndexFlatIP(dim)
            return faiss.IndexIVFFlat(quantizer, dim, nlist)
        elif index_type.startswith("HNSW"):
            m = int(index_type[4:]) if len(index_type) > 4 else 32
            index = faiss.IndexHNSWFlat(dim, m)
            index.hnsw.efConstruction = 64
            index.hnsw.efSearch = 40
            return index
        else:
            # Default to HNSW32
            index = faiss.IndexHNSWFlat(dim, 32)
            index.hnsw.efConstruction = 64
            index.hnsw.efSearch = 40
            return index

    async def initialize(self) -> None:
        """Initialize or load FAISS index."""
        index_file = self._index_path / "index.faiss"
        meta_file = self._index_path / "metadata.pkl"

        if index_file.exists() and meta_file.exists():
            # Load existing index
            self._index = faiss.read_index(str(index_file))
            with open(meta_file, "rb") as f:
                data = pickle.load(f)
                self._id_to_idx = data["id_to_idx"]
                self._idx_to_record = data["idx_to_record"]
                self._next_idx = data["next_idx"]
        else:
            # Create new index
            self._index = self._create_index()

    async def close(self) -> None:
        """Save and close index."""
        if self.config.save_on_update:
            await self._save()

    async def _save(self) -> None:
        """Save index to disk."""
        if self._index is None:
            return

        index_file = self._index_path / "index.faiss"
        meta_file = self._index_path / "metadata.pkl"

        faiss.write_index(self._index, str(index_file))

        with open(meta_file, "wb") as f:
            pickle.dump({
                "id_to_idx": self._id_to_idx,
                "idx_to_record": self._idx_to_record,
                "next_idx": self._next_idx,
            }, f)

    async def upsert(self, records: list[VectorRecord]) -> int:
        """Insert or update vectors."""
        if not records or self._index is None:
            return 0

        # Prepare embeddings
        embeddings = np.array([r.embedding for r in records], dtype=np.float32)

        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)

        # Track which records are new vs updates
        new_records = []
        update_indices = []

        for record in records:
            if record.id in self._id_to_idx:
                # Update existing
                idx = self._id_to_idx[record.id]
                # FAISS doesn't support direct update, so we mark for rebuild
                update_indices.append(idx)
                self._idx_to_record[idx] = record
            else:
                # New record
                new_records.append(record)
                self._id_to_idx[record.id] = self._next_idx
                self._idx_to_record[self._next_idx] = record
                self._next_idx += 1

        if new_records:
            new_embeddings = np.array([r.embedding for r in new_records], dtype=np.float32)
            faiss.normalize_L2(new_embeddings)
            self._index.add(new_embeddings)

        # If there were updates, we need to rebuild (FAISS limitation)
        if update_indices:
            await self._rebuild()

        if self.config.save_on_update:
            await self._save()

        return len(records)

    async def _rebuild(self) -> None:
        """Rebuild index from all records."""
        if self._index is None:
            return

        # Get all embeddings in order
        all_embeddings = []
        for i in range(self._next_idx):
            if i in self._idx_to_record:
                all_embeddings.append(self._idx_to_record[i].embedding)
            else:
                all_embeddings.append([0.0] * self.config.dimensions)

        if not all_embeddings:
            self._index = self._create_index()
            return

        embeddings_array = np.array(all_embeddings, dtype=np.float32)
        faiss.normalize_L2(embeddings_array)

        # Create new index and add all
        self._index = self._create_index()
        self._index.add(embeddings_array)

    async def delete(self, ids: list[UUID]) -> int:
        """Delete vectors by IDs (marks for rebuild)."""
        if not ids or self._index is None:
            return 0

        deleted = 0
        for id in ids:
            if id in self._id_to_idx:
                idx = self._id_to_idx.pop(id)
                self._idx_to_record.pop(idx, None)
                deleted += 1

        if deleted > 0:
            await self._rebuild()
            if self.config.save_on_update:
                await self._save()

        return deleted

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        """Search for similar vectors."""
        if self._index is None or self._index.ntotal == 0:
            return []

        # Prepare query
        query = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(query)

        # Search
        k = min(top_k * 2, self._index.ntotal)  # Get more for filtering
        scores, indices = self._index.search(query, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            record = self._idx_to_record.get(idx)
            if not record:
                continue

            # Apply metadata filter
            if filter_metadata:
                match = True
                for key, value in filter_metadata.items():
                    if record.metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            results.append((record, float(score)))

            if len(results) >= top_k:
                break

        return results

    async def get_stats(self) -> dict[str, Any]:
        """Get indexer statistics."""
        return {
            "total_vectors": self._index.ntotal if self._index else 0,
            "dimensions": self.config.dimensions,
            "index_type": self.config.index_type,
            "index_path": str(self._index_path),
        }
