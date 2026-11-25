"""
ContextForge Ingestion Pipeline Integration Tests

End-to-end tests for the ingestion pipeline.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from contextforge.ingestion import (
    ChunkerRegistry,
    EmbedderRegistry,
    IngestionPipeline,
    LoaderRegistry,
)
from contextforge.storage.database import close_db, get_session, init_db
from contextforge.storage.repositories import (
    ChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def db():
    """Initialize database for tests."""
    await init_db()
    yield
    await close_db()


@pytest_asyncio.fixture
async def session(db):
    """Get database session."""
    async with get_session() as session:
        yield session


@pytest.fixture
def sample_pdf_content() -> bytes:
    """Create a simple PDF for testing."""
    # This is a minimal PDF content
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 100 700 Td (Test PDF) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000206 00000 n \ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n299\n%%EOF"


@pytest.fixture
def sample_markdown() -> str:
    """Sample markdown content."""
    return """# Test Document

This is a test markdown document.

## Section 1

Content for section 1.

## Section 2

Content for section 2 with **bold** and *italic* text.

```python
def hello():
    print("Hello, World!")
```

## Section 3

Final section with a [link](https://example.com).
"""


@pytest.fixture
def temp_markdown_file(sample_markdown: str) -> Path:
    """Create temporary markdown file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(sample_markdown)
        return Path(f.name)


@pytest.fixture
def temp_pdf_file(sample_pdf_content: bytes) -> Path:
    """Create temporary PDF file."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(sample_pdf_content)
        return Path(f.name)


# =============================================================================
# Test Markdown Loader
# =============================================================================

class TestMarkdownLoader:
    """Tests for Markdown loader integration."""

    @pytest.mark.asyncio
    async def test_load_markdown(self, temp_markdown_file: Path):
        """Test loading markdown file."""
        loader_class = LoaderRegistry.get("markdown")
        assert loader_class is not None

        loader = loader_class()
        result = await loader.load(str(temp_markdown_file))

        assert result.content != ""
        assert "Test Document" in result.content
        assert result.metadata["source_type"] == "markdown"
        assert result.title == "Test Document"

    @pytest.mark.asyncio
    async def test_validate_markdown(self, temp_markdown_file: Path):
        """Test validating markdown file."""
        loader_class = LoaderRegistry.get("markdown")
        loader = loader_class()

        is_valid = await loader.validate_source(str(temp_markdown_file))
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        """Test loading nonexistent file."""
        loader_class = LoaderRegistry.get("markdown")
        loader = loader_class()

        is_valid = await loader.validate_source("/nonexistent/file.md")
        assert is_valid is False


# =============================================================================
# Test Chunking Integration
# =============================================================================

class TestChunkingIntegration:
    """Tests for chunking integration."""

    @pytest.mark.asyncio
    async def test_fixed_chunking(self, sample_markdown: str):
        """Test fixed chunking strategy."""
        chunker_class = ChunkerRegistry.get("fixed")
        assert chunker_class is not None

        chunker = chunker_class()
        chunks = chunker.chunk(sample_markdown)

        assert len(chunks) > 0
        assert all(c.metadata["strategy"] == "fixed" for c in chunks)

    @pytest.mark.asyncio
    async def test_semantic_chunking(self, sample_markdown: str):
        """Test semantic chunking strategy."""
        chunker_class = ChunkerRegistry.get("semantic")
        assert chunker_class is not None

        chunker = chunker_class()
        chunks = chunker.chunk(sample_markdown)

        assert len(chunks) > 0
        assert all(c.metadata["strategy"] == "semantic" for c in chunks)

    @pytest.mark.asyncio
    async def test_hierarchical_chunking(self, sample_markdown: str):
        """Test hierarchical chunking strategy."""
        chunker_class = ChunkerRegistry.get("hierarchical")
        assert chunker_class is not None

        chunker = chunker_class()
        chunks = chunker.chunk(sample_markdown)

        assert len(chunks) > 0
        parents = chunker.get_parent_chunks(chunks)
        children = chunker.get_child_chunks(chunks)
        assert len(parents) > 0
        assert len(children) > 0


# =============================================================================
# Test Embedding Integration
# =============================================================================

class TestEmbeddingIntegration:
    """Tests for embedding integration."""

    @pytest.mark.asyncio
    async def test_local_embedding(self, sample_markdown: str):
        """Test local embedding provider."""
        embedder_class = EmbedderRegistry.get("local")
        assert embedder_class is not None

        embedder = embedder_class()
        embedding = embedder.embed(sample_markdown[:100])

        assert isinstance(embedding, list)
        assert len(embedding) == embedder.dimensions
        assert all(isinstance(x, float) for x in embedding)

    @pytest.mark.asyncio
    async def test_batch_embedding(self, sample_markdown: str):
        """Test batch embedding."""
        embedder_class = EmbedderRegistry.get("local")
        embedder = embedder_class()

        texts = [sample_markdown[:50], sample_markdown[50:100], sample_markdown[100:150]]
        embeddings = embedder.embed_batch(texts)

        assert len(embeddings) == 3
        assert all(len(e) == embedder.dimensions for e in embeddings)


# =============================================================================
# Test Full Pipeline Integration
# =============================================================================

class TestFullPipeline:
    """Tests for full ingestion pipeline."""

    @pytest.mark.asyncio
    async def test_ingest_markdown_pipeline(
        self,
        session,
        temp_markdown_file: Path,
    ):
        """Test full ingestion pipeline with markdown."""
        # Create pipeline with local embedder and FAISS (for testing)
        pipeline = IngestionPipeline.from_config(
            source_type="markdown",
            strategy="fixed",
            embedding_provider="local",
            vector_store="faiss",
        )

        await pipeline.initialize()

        try:
            result = await pipeline.ingest(
                str(temp_markdown_file),
                strategy="fixed",
                embedding_provider="local",
            )

            assert result.success is True
            assert result.document_id is not None
            assert result.chunk_count > 0
            assert result.strategy == "fixed"
            assert result.embedding_provider == "local"

            # Verify document was stored
            doc_repo = DocumentRepository(session)
            document = await doc_repo.get_by_id(result.document_id)
            assert document is not None
            assert document.chunk_count == result.chunk_count

            # Verify chunks were stored
            chunk_repo = ChunkRepository(session)
            chunks = await chunk_repo.get_by_document(result.document_id)
            assert len(chunks) == result.chunk_count

            # Verify job was recorded
            job_repo = IngestionJobRepository(session)
            job = await job_repo.get_by_id(result.job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.chunk_count == result.chunk_count

        finally:
            await pipeline.close()

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, session, temp_markdown_file: Path):
        """Test that duplicate documents are detected."""
        pipeline = IngestionPipeline.from_config(
            source_type="markdown",
            strategy="fixed",
            embedding_provider="local",
            vector_store="faiss",
        )

        await pipeline.initialize()

        try:
            # First ingestion
            result1 = await pipeline.ingest(
                str(temp_markdown_file),
                strategy="fixed",
                embedding_provider="local",
            )
            assert result1.success is True

            # Second ingestion (should detect duplicate)
            result2 = await pipeline.ingest(
                str(temp_markdown_file),
                strategy="fixed",
                embedding_provider="local",
            )

            # Should succeed but return existing document
            assert result2.success is True
            assert result2.document_id == result1.document_id
            assert result2.chunk_count == result1.chunk_count

        finally:
            await pipeline.close()

    @pytest.mark.asyncio
    async def test_different_strategies_produce_different_chunks(
        self,
        session,
        temp_markdown_file: Path,
    ):
        """Test that different strategies produce different chunk counts."""
        strategies = ["fixed", "semantic", "hierarchical"]
        results = {}

        for strategy in strategies:
            pipeline = IngestionPipeline.from_config(
                source_type="markdown",
                strategy=strategy,
                embedding_provider="local",
                vector_store="faiss",
            )

            await pipeline.initialize()

            try:
                result = await pipeline.ingest(
                    str(temp_markdown_file),
                    strategy=strategy,
                    embedding_provider="local",
                )
                results[strategy] = result.chunk_count
            finally:
                await pipeline.close()

        # Different strategies should produce different chunk counts
        # (at least hierarchical should be different due to parent-child)
        assert results["hierarchical"] > results["fixed"]


# =============================================================================
# Test Vector Search Integration
# =============================================================================

class TestVectorSearch:
    """Tests for vector search integration."""

    @pytest.mark.asyncio
    async def test_vector_search_after_ingestion(
        self,
        session,
        temp_markdown_file: Path,
    ):
        """Test that vectors can be searched after ingestion."""
        pipeline = IngestionPipeline.from_config(
            source_type="markdown",
            strategy="fixed",
            embedding_provider="local",
            vector_store="faiss",
        )

        await pipeline.initialize()

        try:
            result = await pipeline.ingest(
                str(temp_markdown_file),
                strategy="fixed",
                embedding_provider="local",
            )

            # Search for similar content
            from contextforge.ingestion.indexers import FaissIndexer
            indexer = FaissIndexer()
            await indexer.initialize()

            # Use the same embedder to create query
            from contextforge.ingestion.embedders import LocalEmbedder
            embedder = LocalEmbedder()
            query_embedding = embedder.embed("test document section")

            results = await indexer.search(query_embedding, top_k=5)

            assert len(results) > 0
            # Should find the document we just ingested
            found = any(
                str(r[0].document_id) == str(result.document_id)
                for r in results
            )
            assert found

            await indexer.close()

        finally:
            await pipeline.close()


# =============================================================================
# Test Error Handling
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in pipeline."""

    @pytest.mark.asyncio
    async def test_invalid_source_type(self):
        """Test handling of invalid source type."""
        with pytest.raises(ValueError, match="Unknown source type"):
            IngestionPipeline.from_config(
                source_type="invalid_type",
                strategy="fixed",
                embedding_provider="local",
            )

    @pytest.mark.asyncio
    async def test_invalid_strategy(self):
        """Test handling of invalid chunking strategy."""
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            IngestionPipeline.from_config(
                source_type="markdown",
                strategy="invalid_strategy",
                embedding_provider="local",
            )

    @pytest.mark.asyncio
    async def test_invalid_embedding_provider(self):
        """Test handling of invalid embedding provider."""
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            IngestionPipeline.from_config(
                source_type="markdown",
                strategy="fixed",
                embedding_provider="invalid_provider",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
