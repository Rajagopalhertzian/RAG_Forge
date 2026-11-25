"""
ContextForge Local Embedder

Local embedding using sentence-transformers (BGE, E5, etc.).
"""

from __future__ import annotations

from typing import Any

from contextforge.config import settings
from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderConfig, EmbedderRegistry


class LocalEmbedderConfig(EmbedderConfig):
    """Configuration for local embedder."""

    model_name: str = "BAAI/bge-m3"
    device: str = "cpu"  # cpu, cuda, mps
    normalize_embeddings: bool = True
    trust_remote_code: bool = False


@EmbedderRegistry.register
class LocalEmbedder(BaseEmbedder):
    """Local embedding provider using sentence-transformers."""

    provider_name = "local"
    DEFAULT_MODEL_NAME = "BAAI/bge-m3"

    def __init__(self, config: LocalEmbedderConfig | None = None):
        config = config or LocalEmbedderConfig()

        # Set defaults from settings
        if not config.model_name:
            config.model_name = settings.LOCAL_EMBEDDING_MODEL
        if not config.dimensions:
            config.dimensions = settings.LOCAL_EMBEDDING_DIMENSIONS
        if not config.device:
            config.device = settings.LOCAL_EMBEDDING_DEVICE
        if not config.batch_size:
            config.batch_size = settings.LOCAL_EMBEDDING_BATCH_SIZE

        super().__init__(config)

        self._model = None
        self._init_model()

    def _init_model(self):
        """Initialize the sentence-transformers model."""
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(
            self.config.model_name,
            device=self.config.device,
            trust_remote_code=self.config.trust_remote_code,
        )

        # Set default dimensions if not specified
        if self.config.dimensions == 1024:  # Default
            # Get actual dimensions from model
            test_emb = self._model.encode(["test"], convert_to_numpy=True)
            self.config.dimensions = test_emb.shape[1]

    @property
    def model_name(self) -> str:
        return self.config.model_name

    @property
    def dimensions(self) -> int:
        return self.config.dimensions

    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        embedding = self._model.encode(
            [text],
            batch_size=1,
            normalize_embeddings=self.config.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embedding[0].tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        all_embeddings = []

        for batch in self._batch_iter(texts):
            embeddings = self._model.encode(
                batch,
                batch_size=len(batch),
                normalize_embeddings=self.config.normalize_embeddings,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            all_embeddings.extend(embeddings.tolist())

        return all_embeddings

    async def aembed(self, text: str) -> list[float]:
        """Async embed a single text."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed, text)

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch of texts."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_batch, texts)

    def get_model_info(self) -> dict[str, Any]:
        """Get model information."""
        return {
            "model_name": self.config.model_name,
            "dimensions": self.dimensions,
            "device": self.config.device,
            "max_seq_length": getattr(self._model, "max_seq_length", None),
        }
