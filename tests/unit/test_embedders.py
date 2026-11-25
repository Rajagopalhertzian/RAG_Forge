"""
ContextForge Embedder Unit Tests

Tests for all embedding providers.
"""

from __future__ import annotations

import numpy as np
import pytest

from contextforge.ingestion.embedders import (
    BedrockEmbedder,
    BedrockEmbedderConfig,
    EmbedderRegistry,
    LocalEmbedder,
    LocalEmbedderConfig,
    OpenAIEmbedder,
    OpenAIEmbedderConfig,
    create_golden_set,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_texts() -> list[str]:
    """Sample texts for testing."""
    return [
        "This is a test document about machine learning.",
        "Another document discussing deep learning techniques.",
        "A third text about natural language processing.",
        "Short text.",
        "A much longer document that contains multiple sentences and covers various topics in artificial intelligence including neural networks, transformers, and attention mechanisms.",
        "An additional document about computer vision and image recognition using convolutional neural networks.",
    ]


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.data = [
        MagicMock(embedding=[0.1] * 1536),
        MagicMock(embedding=[0.2] * 1536),
    ]
    return mock


# =============================================================================
# OpenAI Embedder Tests (Mocked)
# =============================================================================

class TestOpenAIEmbedder:
    """Tests for OpenAIEmbedder."""

    def test_config_defaults(self):
        """Test default configuration."""
        config = OpenAIEmbedderConfig()
        assert config.model_name == "text-embedding-3-large"
        assert config.dimensions == 3072
        assert config.batch_size == 32

    def test_provider_name(self):
        """Test provider name property."""
        config = OpenAIEmbedderConfig()
        embedder = OpenAIEmbedder(config)
        assert embedder.provider_name == "openai"

    def test_dimensions_property(self):
        """Test dimensions property."""
        config = OpenAIEmbedderConfig(dimensions=1536)
        embedder = OpenAIEmbedder(config)
        assert embedder.dimensions == 1536


# =============================================================================
# Bedrock Embedder Tests (Mocked)
# =============================================================================

class TestBedrockEmbedder:
    """Tests for BedrockEmbedder."""

    def test_config_defaults(self):
        """Test default configuration."""
        config = BedrockEmbedderConfig()
        assert config.model_id == "amazon.titan-embed-text-v2:0"
        assert config.dimensions == 1024
        assert config.region == "us-east-1"

    def test_provider_name(self):
        """Test provider name property."""
        config = BedrockEmbedderConfig()
        embedder = BedrockEmbedder(config)
        assert embedder.provider_name == "bedrock"

    def test_model_config_titan(self):
        """Test Titan model configuration."""
        config = BedrockEmbedderConfig(model_id="amazon.titan-embed-text-v1")
        embedder = BedrockEmbedder(config)
        assert embedder.dimensions == 1536

    def test_model_config_cohere(self):
        """Test Cohere model configuration."""
        config = BedrockEmbedderConfig(model_id="cohere.embed-english-v3")
        embedder = BedrockEmbedder(config)
        assert embedder.dimensions == 1024
        assert embedder.model_config.get("is_batch") is True


# =============================================================================
# Local Embedder Tests
# =============================================================================

class TestLocalEmbedder:
    """Tests for LocalEmbedder."""

    def test_config_defaults(self):
        """Test default configuration."""
        config = LocalEmbedderConfig()
        assert config.model_name == "BAAI/bge-m3"
        assert config.device == "cpu"
        assert config.normalize_embeddings is True

    def test_provider_name(self):
        """Test provider name property."""
        config = LocalEmbedderConfig()
        embedder = LocalEmbedder(config)
        assert embedder.provider_name == "local"

    @pytest.mark.slow
    def test_embed_single(self, sample_texts: list[str]):
        """Test embedding a single text (requires model download)."""
        config = LocalEmbedderConfig(batch_size=2)
        embedder = LocalEmbedder(config)

        embedding = embedder.embed(sample_texts[0])

        assert isinstance(embedding, list)
        assert len(embedding) == embedder.dimensions
        assert all(isinstance(x, float) for x in embedding)

    @pytest.mark.slow
    def test_embed_batch(self, sample_texts: list[str]):
        """Test embedding a batch of texts."""
        config = LocalEmbedderConfig(batch_size=2)
        embedder = LocalEmbedder(config)

        embeddings = embedder.embed_batch(sample_texts)

        assert len(embeddings) == len(sample_texts)
        assert all(len(e) == embedder.dimensions for e in embeddings)

    @pytest.mark.slow
    def test_normalization(self, sample_texts: list[str]):
        """Test that embeddings are normalized."""
        config = LocalEmbedderConfig(normalize_embeddings=True)
        embedder = LocalEmbedder(config)

        embeddings = embedder.embed_batch(sample_texts[:2])

        for emb in embeddings:
            norm = np.linalg.norm(emb)
            assert abs(norm - 1.0) < 1e-5

    @pytest.mark.slow
    def test_no_normalization(self, sample_texts: list[str]):
        """Test embeddings without normalization."""
        config = LocalEmbedderConfig(normalize_embeddings=False)
        embedder = LocalEmbedder(config)

        embeddings = embedder.embed_batch(sample_texts[:2])

        for emb in embeddings:
            norm = np.linalg.norm(emb)
            # Not normalized, so norm != 1
            assert norm > 0


# =============================================================================
# Registry Tests
# =============================================================================

class TestEmbedderRegistry:
    """Tests for EmbedderRegistry."""

    def test_list_providers(self):
        """Test listing all providers."""
        providers = EmbedderRegistry.list_providers()

        assert "openai" in providers
        assert "bedrock" in providers
        assert "local" in providers

    def test_get_embedder(self):
        """Test getting embedder by name."""
        embedder_class = EmbedderRegistry.get("local")
        assert embedder_class is not None

        embedder = EmbedderRegistry.get_instance("local")
        assert embedder is not None
        assert embedder.provider_name == "local"

    def test_get_by_model_name(self):
        """Test getting embedder by model name."""
        embedder_class = EmbedderRegistry.get("BAAI/bge-m3")
        assert embedder_class is not None

    def test_unknown_provider(self):
        """Test getting unknown provider."""
        embedder = EmbedderRegistry.get_instance("unknown")
        assert embedder is None


# =============================================================================
# Evaluation Tests
# =============================================================================

class TestEmbeddingEvaluation:
    """Tests for embedding evaluation utilities."""

    def test_create_golden_set(self, sample_texts: list[str]):
        """Test creating golden set."""
        queries, ground_truth = create_golden_set(
            sample_texts,
            n_queries=2,
            n_relevant_per_query=2,
        )

        assert len(queries) == 2
        assert len(ground_truth) == 2
        assert all(isinstance(v, list) for v in ground_truth.values())
        assert all(len(v) == 2 for v in ground_truth.values())

    def test_create_golden_set_insufficient_texts(self):
        """Test golden set with insufficient texts."""
        texts = ["short"]

        with pytest.raises(ValueError, match="Not enough texts"):
            create_golden_set(texts, n_queries=2, n_relevant_per_query=2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
