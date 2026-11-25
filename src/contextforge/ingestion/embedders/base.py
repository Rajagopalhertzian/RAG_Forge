"""
ContextForge Base Embedder

Abstract base class for embedding providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class EmbedderConfig(BaseModel):
    """Base configuration for embedders."""

    model_name: str = Field(default="")
    dimensions: int = Field(default=1024, ge=1, le=8192)
    batch_size: int = Field(default=32, ge=1, le=512)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    # For local embedder
    device: str | None = Field(default=None)
    normalize_embeddings: bool = Field(default=True)
    trust_remote_code: bool = Field(default=False)


class BaseEmbedder(ABC):
    """Abstract base class for embedding providers."""

    def __init__(self, config: EmbedderConfig):
        self.config = config

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'bedrock', 'local')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensions."""
        pass

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        pass

    async def aembed(self, text: str) -> list[float]:
        """Async embed a single text."""
        # Default implementation runs sync in executor
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed, text)

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch of texts."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_batch, texts)

    def _batch_iter(self, texts: list[str], batch_size: int | None = None):
        """Iterate over texts in batches."""
        batch_size = batch_size or self.config.batch_size
        for i in range(0, len(texts), batch_size):
            yield texts[i:i + batch_size]


class EmbedderRegistry:
    """Registry for managing embedder instances."""

    _embedders: dict[str, type[BaseEmbedder]] = {}

    @classmethod
    def register(cls, embedder_class: type[BaseEmbedder]) -> type[BaseEmbedder]:
        """Register an embedder class."""
        # Use class attributes instead of instantiating
        # Get provider_name and model_name, handling case where they might be properties
        provider_name = getattr(embedder_class, 'provider_name', None)
        model_name = getattr(embedder_class, 'model_name', None)

        # If they're property objects (from abstract base class), try to get the default
        # from a class attribute set after class definition (e.g., DEFAULT_MODEL_NAME)
        if isinstance(provider_name, property):
            provider_name = getattr(embedder_class, 'DEFAULT_PROVIDER_NAME', None)
        if isinstance(model_name, property):
            model_name = getattr(embedder_class, 'DEFAULT_MODEL_NAME', None)

        # Also check for class attributes directly (in case they're not properties)
        if provider_name is None:
            provider_name = embedder_class.__dict__.get('provider_name')
        if model_name is None:
            model_name = embedder_class.__dict__.get('model_name') or embedder_class.__dict__.get('DEFAULT_MODEL_NAME')

        if provider_name:
            cls._embedders[provider_name] = embedder_class
        if model_name:
            cls._embedders[model_name] = embedder_class
        return embedder_class

    @classmethod
    def get(cls, name: str) -> type[BaseEmbedder] | None:
        """Get embedder class by provider or model name."""
        return cls._embedders.get(name)

    @classmethod
    def get_instance(cls, name: str, config: EmbedderConfig | None = None) -> BaseEmbedder | None:
        """Get embedder instance by name."""
        embedder_class = cls.get(name)
        if embedder_class:
            return embedder_class(config)
        return None

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered providers."""
        return list(set(cls._embedders.keys()))
