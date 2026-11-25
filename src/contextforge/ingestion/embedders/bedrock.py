"""
ContextForge Bedrock Embedder

AWS Bedrock embedding provider (Titan, Cohere).
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config as BotocoreConfig

from contextforge.config import settings
from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderConfig, EmbedderRegistry


class BedrockEmbedderConfig(EmbedderConfig):
    """Configuration for Bedrock embedder."""

    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    model_id: str = "amazon.titan-embed-text-v2:0"


# Model configurations
BEDROCK_MODELS = {
    "amazon.titan-embed-text-v1": {
        "dimensions": 1536,
        "input_key": "inputText",
        "output_key": "embedding",
    },
    "amazon.titan-embed-text-v2:0": {
        "dimensions": 1024,
        "input_key": "inputText",
        "output_key": "embedding",
    },
    "amazon.titan-embed-image-v1": {
        "dimensions": 1024,
        "input_key": "inputImage",
        "output_key": "embedding",
    },
    "cohere.embed-english-v3": {
        "dimensions": 1024,
        "input_key": "texts",
        "output_key": "embeddings",
        "is_batch": True,
    },
    "cohere.embed-multilingual-v3": {
        "dimensions": 1024,
        "input_key": "texts",
        "output_key": "embeddings",
        "is_batch": True,
    },
}


@EmbedderRegistry.register
class BedrockEmbedder(BaseEmbedder):
    """AWS Bedrock embedding provider."""

    provider_name = "bedrock"
    DEFAULT_MODEL_NAME = "amazon.titan-embed-text-v2:0"

    def __init__(self, config: BedrockEmbedderConfig | None = None):
        config = config or BedrockEmbedderConfig()

        # Set defaults from settings
        if not config.model_name:
            config.model_name = settings.BEDROCK_EMBEDDING_MODEL
        if not config.dimensions:
            config.dimensions = settings.BEDROCK_EMBEDDING_DIMENSIONS
        if not config.region:
            config.region = settings.AWS_REGION
        if not config.access_key_id:
            config.access_key_id = settings.AWS_ACCESS_KEY_ID
        if not config.secret_access_key:
            config.secret_access_key = settings.AWS_SECRET_ACCESS_KEY

        super().__init__(config)

        # Get model config
        self.model_config = BEDROCK_MODELS.get(config.model_id, {
            "dimensions": config.dimensions,
            "input_key": "inputText",
            "output_key": "embedding",
        })

        # Initialize client
        self._client = None
        self._init_client()

    def _init_client(self):
        """Initialize Bedrock client."""
        session = boto3.Session(
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name=self.config.region,
        )

        self._client = session.client(
            "bedrock-runtime",
            config=BotocoreConfig(
                retries={"max_attempts": self.config.max_retries},
                connect_timeout=self.config.timeout,
                read_timeout=self.config.timeout,
            ),
        )

    @property
    def model_name(self) -> str:
        return self.config.model_id

    @property
    def dimensions(self) -> int:
        return self.model_config.get("dimensions", self.config.dimensions)

    def _prepare_request(self, texts: list[str]) -> dict[str, Any]:
        """Prepare request body for Bedrock."""
        input_key = self.model_config["input_key"]
        is_batch = self.model_config.get("is_batch", False)

        if is_batch:
            return {input_key: texts}
        else:
            # Single text - take first
            return {input_key: texts[0]}

    def _parse_response(self, response_body: bytes, count: int) -> list[list[float]]:
        """Parse response from Bedrock."""
        data = json.loads(response_body)
        output_key = self.model_config["output_key"]
        is_batch = self.model_config.get("is_batch", False)

        if is_batch:
            return data[output_key]
        else:
            return [data[output_key]]

    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        body = self._prepare_request([text])

        response = self._client.invoke_model(
            modelId=self.config.model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        embeddings = self._parse_response(response["body"].read(), 1)
        return embeddings[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        all_embeddings = []

        for batch in self._batch_iter(texts):
            body = self._prepare_request(batch)

            response = self._client.invoke_model(
                modelId=self.config.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            batch_embeddings = self._parse_response(response["body"].read(), len(batch))
            all_embeddings.extend(batch_embeddings)

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
