"""
ContextForge Embedders Package

Embedding providers for vector generation.
"""

from contextforge.ingestion.embedders.base import BaseEmbedder, EmbedderConfig, EmbedderRegistry
from contextforge.ingestion.embedders.bedrock import BedrockEmbedder, BedrockEmbedderConfig
from contextforge.ingestion.embedders.evaluation import (
    EmbeddingEvaluator,
    EmbeddingMetrics,
    create_golden_set,
)
from contextforge.ingestion.embedders.local import LocalEmbedder, LocalEmbedderConfig
from contextforge.ingestion.embedders.openai import OpenAIEmbedder, OpenAIEmbedderConfig

__all__ = [
    "BaseEmbedder",
    "EmbedderConfig",
    "EmbedderRegistry",
    "OpenAIEmbedder",
    "OpenAIEmbedderConfig",
    "BedrockEmbedder",
    "BedrockEmbedderConfig",
    "LocalEmbedder",
    "LocalEmbedderConfig",
    "EmbeddingEvaluator",
    "EmbeddingMetrics",
    "create_golden_set",
]
