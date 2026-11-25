"""
ContextForge Chunker Unit Tests

Tests for all chunking strategies.
"""

from __future__ import annotations

import pytest

from contextforge.ingestion.chunkers import (
    ChunkerRegistry,
    CodeChunker,
    CodeChunkerConfig,
    FixedChunker,
    FixedChunkerConfig,
    HierarchicalChunker,
    HierarchicalChunkerConfig,
    SemanticChunker,
    SemanticChunkerConfig,
    create_ground_truth_boundaries,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_text() -> str:
    """Sample text for testing."""
    return """
# Introduction

This is a sample document for testing chunking strategies.
It contains multiple paragraphs and sections. We need enough text to test chunking with overlap.

## Section 1

First section content goes here. It has several sentences.
Each sentence should be considered for semantic boundaries.
The chunker should respect paragraph boundaries.
We are adding more content to ensure the text is long enough to be split into multiple chunks.
This is important for testing overlap behavior and multi-chunk scenarios.

## Section 2

Second section with different content.
More sentences to test the chunking behavior.
We want to ensure proper splitting happens correctly.
Adding more text here to make sure we exceed the minimum chunk size.
This paragraph has multiple sentences that will help with token counting.
The chunker should handle this appropriately.

## Section 3

Third section with even more content for testing.
We need to ensure there is enough text to create multiple chunks.
This is especially important for the overlap test which requires at least two chunks.
Each sentence adds to the token count.
We continue adding content to make the text sufficiently long.
This should create multiple chunks when using a small chunk size.

## Section 4

Final section with concluding remarks.
This should be the last chunk in hierarchical mode.
Even more text here to ensure proper chunking behavior.
The test needs enough content to verify the chunker works correctly.
""".strip()


@pytest.fixture
def sample_code() -> str:
    """Sample Python code for testing."""
    return '''
"""Module docstring."""

import os
from typing import List

CONSTANT = "value"

class MyClass:
    """Class docstring."""

    def __init__(self, name: str):
        self.name = name

    def method_one(self) -> str:
        """Method docstring."""
        return f"Hello {self.name}"

    def method_two(self, x: int) -> int:
        """Another method."""
        return x * 2


def standalone_function(items: List[str]) -> str:
    """Function docstring."""
    return ", ".join(items)


if __name__ == "__main__":
    obj = MyClass("World")
    print(obj.method_one())
'''


# =============================================================================
# Fixed Chunker Tests
# =============================================================================

class TestFixedChunker:
    """Tests for FixedChunker."""

    def test_basic_chunking(self, sample_text: str):
        """Test basic fixed chunking."""
        config = FixedChunkerConfig(chunk_size=100, chunk_overlap=20)
        chunker = FixedChunker(config)

        chunks = chunker.chunk(sample_text)

        assert len(chunks) > 0
        assert all(c.token_count <= 100 for c in chunks)
        assert all(c.metadata["strategy"] == "fixed" for c in chunks)

    def test_empty_text(self):
        """Test chunking empty text."""
        config = FixedChunkerConfig()
        chunker = FixedChunker(config)

        chunks = chunker.chunk("")

        assert len(chunks) == 0

    def test_single_chunk(self, sample_text: str):
        """Test text that fits in one chunk."""
        config = FixedChunkerConfig(chunk_size=8192)
        chunker = FixedChunker(config)

        chunks = chunker.chunk(sample_text)

        assert len(chunks) == 1

    def test_overlap(self, sample_text: str):
        """Test that chunks have overlap."""
        config = FixedChunkerConfig(chunk_size=100, chunk_overlap=10)
        chunker = FixedChunker(config)

        chunks = chunker.chunk(sample_text)

        assert len(chunks) > 1
        # Check metadata has overlap info
        assert chunks[0].metadata["chunk_overlap"] == 10

    def test_metadata_preservation(self, sample_text: str):
        """Test that metadata is preserved."""
        config = FixedChunkerConfig()
        chunker = FixedChunker(config)

        metadata = {"source": "test", "author": "tester"}
        chunks = chunker.chunk(sample_text, metadata)

        assert all(c.metadata["source"] == "test" for c in chunks)
        assert all(c.metadata["author"] == "tester" for c in chunks)


# =============================================================================
# Semantic Chunker Tests
# =============================================================================

class TestSemanticChunker:
    """Tests for SemanticChunker."""

    def test_basic_chunking(self, sample_text: str):
        """Test basic semantic chunking."""
        config = SemanticChunkerConfig(chunk_size=200, threshold=0.5)
        chunker = SemanticChunker(config)

        chunks = chunker.chunk(sample_text)

        assert len(chunks) > 0
        assert all(c.metadata["strategy"] == "semantic" for c in chunks)

    def test_empty_text(self):
        """Test chunking empty text."""
        config = SemanticChunkerConfig()
        chunker = SemanticChunker(config)

        chunks = chunker.chunk("")

        assert len(chunks) == 0

    def test_threshold_effect(self, sample_text: str):
        """Test that threshold affects chunk count."""
        config_low = SemanticChunkerConfig(chunk_size=200, threshold=0.3)
        config_high = SemanticChunkerConfig(chunk_size=200, threshold=0.9)

        chunker_low = SemanticChunker(config_low)
        chunker_high = SemanticChunker(config_high)

        chunks_low = chunker_low.chunk(sample_text)
        chunks_high = chunker_high.chunk(sample_text)

        # Higher threshold = more boundaries = more chunks
        assert len(chunks_high) >= len(chunks_low)


# =============================================================================
# Hierarchical Chunker Tests
# =============================================================================

class TestHierarchicalChunker:
    """Tests for HierarchicalChunker."""

    def test_basic_chunking(self, sample_text: str):
        """Test hierarchical chunking."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=200,
            child_chunk_size=100,  # Minimum allowed by FixedChunkerConfig
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(sample_text)

        assert len(chunks) > 0

        # Check for parent and child chunks
        parents = chunker.get_parent_chunks(chunks)
        children = chunker.get_child_chunks(chunks)

        assert len(parents) > 0
        assert len(children) > 0
        assert len(parents) + len(children) == len(chunks)

    def test_parent_child_relationship(self, sample_text: str):
        """Test parent-child index relationships."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=200,
            child_chunk_size=100,  # Minimum allowed by FixedChunkerConfig
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(sample_text)
        parents = chunker.get_parent_chunks(chunks)

        # At least one parent should have children
        parents_with_children = [p for p in parents if p.metadata.get("child_indices", [])]
        assert len(parents_with_children) > 0

        for parent in parents_with_children:
            child_indices = parent.metadata.get("child_indices", [])
            assert len(child_indices) > 0

            # Verify children exist
            for idx in child_indices:
                child = next((c for c in chunks if c.index == idx), None)
                assert child is not None
                assert child.metadata["hierarchy_level"] == "child"
                assert child.metadata["parent_index"] == parent.index

    def test_get_children_for_parent(self, sample_text: str):
        """Test getting children for a specific parent."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=200,
            child_chunk_size=100,  # Minimum allowed by FixedChunkerConfig
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(sample_text)
        parents = chunker.get_parent_chunks(chunks)

        if parents:
            parent = parents[0]
            children = chunker.get_children_for_parent(chunks, parent.index)
            assert len(children) == len(parent.metadata.get("child_indices", []))


# =============================================================================
# Code Chunker Tests
# =============================================================================

class TestCodeChunker:
    """Tests for CodeChunker."""

    def test_python_chunking(self, sample_code: str):
        """Test chunking Python code."""
        config = CodeChunkerConfig(max_lines=20)
        chunker = CodeChunker(config)

        metadata = {"file_path": "test.py"}
        chunks = chunker.chunk(sample_code, metadata)

        assert len(chunks) > 0
        assert all(c.metadata["strategy"] == "code" for c in chunks)
        assert all(c.metadata["language"] == "python" for c in chunks)

    def test_node_types(self, sample_code: str):
        """Test that different node types are captured."""
        config = CodeChunkerConfig(max_lines=50)
        chunker = CodeChunker(config)

        metadata = {"file_path": "test.py"}
        chunks = chunker.chunk(sample_code, metadata)

        node_types = {c.metadata.get("node_type") for c in chunks}
        assert "function_definition" in node_types
        assert "class_definition" in node_types

    def test_fallback_for_unknown_language(self):
        """Test fallback for unknown language."""
        config = CodeChunkerConfig(fallback_to_fixed=True)
        chunker = CodeChunker(config)

        text = "This is plain text without code structure."
        chunks = chunker.chunk(text)

        # Should fall back to fixed chunking
        assert len(chunks) > 0
        # Some chunks may have fallback marker


# =============================================================================
# Registry Tests
# =============================================================================

class TestChunkerRegistry:
    """Tests for ChunkerRegistry."""

    def test_list_strategies(self):
        """Test listing all strategies."""
        strategies = ChunkerRegistry.list_strategies()

        assert "fixed" in strategies
        assert "semantic" in strategies
        assert "hierarchical" in strategies
        assert "code" in strategies

    def test_get_chunker(self):
        """Test getting chunker by name."""
        chunker_class = ChunkerRegistry.get("fixed")
        assert chunker_class is not None

        chunker = ChunkerRegistry.get_instance("fixed")
        assert chunker is not None
        assert chunker.strategy_name == "fixed"

    def test_unknown_strategy(self):
        """Test getting unknown strategy."""
        chunker = ChunkerRegistry.get_instance("unknown")
        assert chunker is None


# =============================================================================
# Evaluation Tests
# =============================================================================

class TestChunkingEvaluation:
    """Tests for chunking evaluation utilities."""

    def test_create_ground_truth_paragraph(self, sample_text: str):
        """Test creating ground truth boundaries for paragraphs."""
        boundaries = create_ground_truth_boundaries(sample_text, method="paragraph")

        assert 0 in boundaries
        assert len(sample_text) in boundaries
        assert len(boundaries) > 2  # Should have paragraph boundaries

    def test_create_ground_truth_sentence(self, sample_text: str):
        """Test creating ground truth boundaries for sentences."""
        boundaries = create_ground_truth_boundaries(sample_text, method="sentence")

        assert 0 in boundaries
        assert len(sample_text) in boundaries

    def test_create_ground_truth_section(self, sample_text: str):
        """Test creating ground truth boundaries for sections."""
        boundaries = create_ground_truth_boundaries(sample_text, method="section")

        assert 0 in boundaries
        assert len(sample_text) in boundaries


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
