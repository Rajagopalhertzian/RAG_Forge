"""
ContextForge OpenAI Embedder

OpenAI and Azure OpenAI embedding provider.
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAI

from contextforge.config import settings
from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderConfig, EmbedderRegistry


class OpenAIEmbedderConfig(EmbedderConfig):
    """Configuration for OpenAI embedder."""

    model_name: str = "text-embedding-3-large"
    dimensions: int = 3072
    api_key: str | None = None
    organization: str | None = None
    base_url: str | None = None
    api_version: str | None = None  # For Azure
    azure_endpoint: str | None = None
    azure_deployment: str | None = None


@EmbedderRegistry.register
class OpenAIEmbedder(BaseEmbedder):
    """OpenAI embedding provider."""

    provider_name = "openai"
    DEFAULT_MODEL_NAME = "text-embedding-3-large"

    def __init__(self, config: OpenAIEmbedderConfig | None = None):
        config = config or OpenAIEmbedderConfig()

        # Set defaults from settings
        if not config.model_name:
            config.model_name = settings.OPENAI_EMBEDDING_MODEL
        if not config.dimensions:
            config.dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS
        if not config.api_key:
            config.api_key = settings.OPENAI_API_KEY
        if not config.organization:
            config.organization = settings.OPENAI_ORGANIZATION

        super().__init__(config)

        # Initialize clients
        self._client: OpenAI | None = None
        self._async_client: AsyncOpenAI | None = None

        # Azure configuration
        self._is_azure = bool(config.azure_endpoint and config.azure_deployment)
        if self._is_azure:
            if not config.api_version:
                config.api_version = settings.OPENAI_API_VERSION
            if not config.azure_endpoint:
                config.azure_endpoint = settings.AZURE_OPENAI_ENDPOINT
            if not config.azure_deployment:
                config.azure_deployment = settings.AZURE_OPENAI_DEPLOYMENT_NAME
            if not config.api_key:
                config.api_key = settings.AZURE_OPENAI_API_KEY

    @property
    def model_name(self) -> str:
        return self.config.model_name

    @property
    def dimensions(self) -> int:
        return self.config.dimensions

    @property
    def client(self) -> OpenAI:
        """Get or create sync client."""
        if self._client is None:
            if self._is_azure:
                self._client = OpenAI(
                    api_key=self.config.api_key,
                    azure_endpoint=self.config.azure_endpoint,
                    api_version=self.config.api_version,
                    organization=self.config.organization,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
            else:
                self._client = OpenAI(
                    api_key=self.config.api_key,
                    organization=self.config.organization,
                    base_url=self.config.base_url,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
        return self._client

    @property
    def async_client(self) -> AsyncOpenAI:
        """Get or create async client."""
        if self._async_client is None:
            if self._is_azure:
                self._async_client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    azure_endpoint=self.config.azure_endpoint,
                    api_version=self.config.api_version,
                    organization=self.config.organization,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
            else:
                self._async_client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    organization=self.config.organization,
                    base_url=self.config.base_url,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )
        return self._async_client

    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        response = self.client.embeddings.create(
            model=self.config.azure_deployment if self._is_azure else self.config.model_name,
            input=text,
            dimensions=self.config.dimensions if not self._is_azure else None,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        all_embeddings = []

        for batch in self._batch_iter(texts):
            response = self.client.embeddings.create(
                model=self.config.azure_deployment if self._is_azure else self.config.model_name,
                input=batch,
                dimensions=self.config.dimensions if not self._is_azure else None,
            )
            batch_embeddings = [d.embedding for d in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def aembed(self, text: str) -> list[float]:
        """Async embed a single text."""
        response = await self.async_client.embeddings.create(
            model=self.config.azure_deployment if self._is_azure else self.config.model_name,
            input=text,
            dimensions=self.config.dimensions if not self._is_azure else None,
        )
        return response.data[0].embedding

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch of texts."""
        all_embeddings = []

        for batch in self._batch_iter(texts):
            response = await self.async_client.embeddings.create(
                model=self.config.azure_deployment if self._is_azure else self.config.model_name,
                input=batch,
                dimensions=self.config.dimensions if not self._is_azure else None,
            )
            batch_embeddings = [d.embedding for d in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
