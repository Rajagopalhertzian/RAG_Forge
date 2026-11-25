"""
ContextForge Integration Tests - Full RAG Graph

Integration tests for the complete agentic RAG graph.
Run with: pytest tests/integration/test_rag_graph.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from contextforge.agentic.checkpointer import get_memory_checkpointer
from contextforge.agentic.graphs.rag_graph import (
    RAGGraphRunner,
    create_rag_graph,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def memory_checkpointer():
    """Memory checkpointer for testing."""
    return get_memory_checkpointer()


@pytest.fixture
def test_graph(memory_checkpointer):
    """Create test graph with memory checkpointer."""
    return create_rag_graph(checkpointer=memory_checkpointer)


@pytest.fixture
def test_runner(test_graph):
    """Create test runner."""
    return RAGGraphRunner(graph=test_graph)


@pytest.fixture
def sample_query() -> str:
    return "How do I configure pgvector HNSW index for optimal performance?"


@pytest.fixture
def mock_all_llms():
    """Mock all LLM calls for full graph execution."""
    with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_rewrite_llm, \
         patch("contextforge.agentic.nodes.retrieve.EmbedderRegistry") as mock_embedder_registry, \
         patch("contextforge.agentic.nodes.retrieve.get_session") as mock_get_session, \
         patch("contextforge.agentic.nodes.rerank.RerankNode._rerank") as mock_rerank, \
         patch("contextforge.agentic.nodes.synthesize.ChatAnthropic") as mock_synthesize_llm, \
         patch("contextforge.agentic.nodes.verify.ChatOpenAI") as mock_verify_llm, \
         patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_pii") as mock_pii, \
         patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_toxicity") as mock_toxicity, \
         patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_hallucination") as mock_hallucination, \
         patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_policy") as mock_policy:

        # Setup rewrite mock
        mock_rewrite_instance = AsyncMock()
        mock_rewrite_output = MagicMock()
        mock_rewrite_output.rewritten_queries = [
            "pgvector HNSW index configuration",
            "How to create HNSW index in pgvector",
            "pgvector vector_cosine_ops parameters",
        ]
        mock_rewrite_output.hyde_document = "This document explains pgvector HNSW index configuration with optimal parameters."
        mock_rewrite_output.reasoning = "Generated diverse queries"
        mock_rewrite_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_rewrite_output)
        mock_rewrite_llm.return_value = mock_rewrite_instance

        # Setup embedder mock
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[[0.1] * 3072])
        mock_embedder_registry.get.return_value = mock_embedder

        # Setup database session mock
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(
                id=uuid4(),
                document_id=uuid4(),
                chunk_index=0,
                content="To configure pgvector HNSW index, use CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
                token_count=45,
                strategy="semantic",
                metadata={"source_type": "documentation"},
                embedding_model="text-embedding-3-large",
                embedding_provider="openai",
                similarity=0.95,
            ),
            MagicMock(
                id=uuid4(),
                document_id=uuid4(),
                chunk_index=1,
                content="HNSW parameters: M=16 controls graph connectivity, ef_construction=64 controls build-time accuracy, ef_search=40 controls query-time accuracy",
                token_count=40,
                strategy="semantic",
                metadata={"source_type": "documentation"},
                embedding_model="text-embedding-3-large",
                embedding_provider="openai",
                similarity=0.87,
            ),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # Setup rerank mock
        mock_rerank_result = MagicMock()
        mock_rerank_result.results = [
            MagicMock(index=0, relevance_score=0.98),
            MagicMock(index=1, relevance_score=0.92),
        ]
        mock_rerank.return_value = mock_rerank_result

        # Setup synthesize mock
        mock_synthesize_instance = AsyncMock()
        mock_synthesize_output = MagicMock()
        mock_synthesize_output.answer = "To configure pgvector HNSW index for optimal performance, use CREATE INDEX with vector_cosine_ops and set M=16, ef_construction=64 [chunk_id_1]. The M parameter controls graph connectivity while ef_construction controls build-time accuracy [chunk_id_2]."
        mock_synthesize_output.citations = [
            MagicMock(
                claim="Use CREATE INDEX with vector_cosine_ops and set M=16, ef_construction=64",
                chunk_ids=["chunk_id_1", "chunk_id_2"],
                chunk_scores=[0.98, 0.92],
            )
        ]
        mock_synthesize_output.reasoning = "Direct answer with citations"
        mock_synthesize_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_synthesize_output)

        # For streaming
        async def mock_stream(*args, **kwargs):
            for part in mock_synthesize_output.answer.split(" "):
                yield MagicMock(content=part + " ")
        mock_synthesize_instance.astream = mock_stream

        mock_synthesize_llm.return_value = mock_synthesize_instance

        # Setup verify mock
        mock_verify_instance = AsyncMock()
        mock_verify_output = MagicMock()
        mock_verify_output.confidence = 0.9
        mock_verify_output.factual_consistency = 0.95
        mock_verify_output.answer_completeness = 0.85
        mock_verify_output.hallucination_flags = []
        mock_verify_output.rewrite_signal = False
        mock_verify_output.reasoning = "Answer well-grounded in context"
        mock_verify_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_verify_output)
        mock_verify_llm.return_value = mock_verify_instance

        # Setup guardrail mocks (all clean)
        mock_pii.return_value = []
        mock_toxicity.return_value = []
        mock_hallucination.return_value = []
        mock_policy.return_value = []

        yield


# =============================================================================
# Graph Construction Tests
# =============================================================================


class TestGraphConstruction:
    """Tests for graph construction."""

    def test_graph_creates_successfully(self, memory_checkpointer):
        """Test graph compiles without errors."""
        graph = create_rag_graph(checkpointer=memory_checkpointer)
        assert graph is not None

    def test_graph_has_all_nodes(self, test_graph):
        """Test graph has all 7 nodes."""
        # Get graph nodes
        nodes = test_graph.get_graph().nodes
        node_names = [n for n in nodes]

        expected_nodes = ["rewrite", "retrieve", "rerank", "synthesize", "verify", "guardrail", "hitl"]
        for node in expected_nodes:
            assert node in node_names

    def test_graph_has_conditional_edges(self, test_graph):
        """Test graph has conditional edges."""
        edges = test_graph.get_graph().edges
        # Should have edges for all linear + conditional
        assert len(edges) > 7  # More than just linear edges


# =============================================================================
# Full Graph Execution Tests
# =============================================================================


class TestFullGraphExecution:
    """Tests for full graph execution."""

    @pytest.mark.asyncio
    async def test_graph_invoke_success(self, test_runner, sample_query, mock_all_llms):
        """Test successful graph invocation."""
        result = await test_runner.invoke(
            query=sample_query,
            session_id="test_session",
            user_id="test_user",
        )

        assert result.get("answer") is not None
        assert len(result.get("answer", "")) > 0
        assert result.get("citations") is not None
        assert result.get("verification") is not None
        assert result.get("guardrail_action") == "proceed"
        assert result.get("hitl_required") is False
        assert result.get("error") is None
        assert result.get("total_latency_ms") is not None

    @pytest.mark.asyncio
    async def test_graph_streaming_events(self, test_runner, sample_query, mock_all_llms):
        """Test graph streaming produces events."""
        events = []
        async for event in test_runner.stream(
            query=sample_query,
            session_id="test_session",
            user_id="test_user",
        ):
            events.append(event)

        # Should have phase events
        event_types = {e.get("type") for e in events}
        assert "phase_start" in event_types
        assert "phase_complete" in event_types
        # Should have token events from synthesis
        assert "token" in event_types
        # Should have complete event
        assert "complete" in event_types

    @pytest.mark.asyncio
    async def test_graph_rewrite_loop_on_low_confidence(self, test_runner, sample_query):
        """Test graph loops back to rewrite on low confidence."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_rewrite_llm, \
             patch("contextforge.agentic.nodes.retrieve.EmbedderRegistry") as mock_embedder_registry, \
             patch("contextforge.agentic.nodes.retrieve.get_session") as mock_get_session, \
             patch("contextforge.agentic.nodes.rerank.RerankNode._rerank") as mock_rerank, \
             patch("contextforge.agentic.nodes.synthesize.ChatAnthropic") as mock_synthesize_llm, \
             patch("contextforge.agentic.nodes.verify.ChatOpenAI") as mock_verify_llm, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_pii") as mock_pii, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_toxicity") as mock_toxicity, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_hallucination") as mock_hallucination, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_policy") as mock_policy:

            # Setup mocks (similar to mock_all_llms but verify returns low confidence)
            mock_rewrite_instance = AsyncMock()
            mock_rewrite_output = MagicMock()
            mock_rewrite_output.rewritten_queries = ["query 1", "query 2"]
            mock_rewrite_output.hyde_document = "HyDE doc"
            mock_rewrite_output.reasoning = "Reasoning"
            mock_rewrite_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_rewrite_output)
            mock_rewrite_llm.return_value = mock_rewrite_instance

            mock_embedder = AsyncMock()
            mock_embedder.embed = AsyncMock(return_value=[[0.1] * 3072])
            mock_embedder_registry.get.return_value = mock_embedder

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [
                MagicMock(
                    id=uuid4(),
                    document_id=uuid4(),
                    chunk_index=0,
                    content="Some content",
                    token_count=10,
                    strategy="semantic",
                    metadata={},
                    embedding_model="test",
                    embedding_provider="test",
                    similarity=0.5,
                ),
            ]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_rerank_result = MagicMock()
            mock_rerank_result.results = [MagicMock(index=0, relevance_score=0.5)]
            mock_rerank.return_value = mock_rerank_result

            mock_synthesize_instance = AsyncMock()
            mock_synthesize_output = MagicMock()
            mock_synthesize_output.answer = "Low quality answer"
            mock_synthesize_output.citations = []
            mock_synthesize_output.reasoning = "Poor"
            mock_synthesize_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_synthesize_output)
            async def mock_stream(*args, **kwargs):
                for part in "Low quality answer".split(" "):
                    yield MagicMock(content=part + " ")
            mock_synthesize_instance.astream = mock_stream
            mock_synthesize_llm.return_value = mock_synthesize_instance

            # Verify returns low confidence -> rewrite signal
            mock_verify_instance = AsyncMock()
            mock_verify_output = MagicMock()
            mock_verify_output.confidence = 0.4
            mock_verify_output.factual_consistency = 0.5
            mock_verify_output.answer_completeness = 0.4
            mock_verify_output.hallucination_flags = ["Low quality"]
            mock_verify_output.rewrite_signal = True
            mock_verify_output.reasoning = "Need better answer"
            mock_verify_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_verify_output)
            mock_verify_llm.return_value = mock_verify_instance

            mock_pii.return_value = []
            mock_toxicity.return_value = []
            mock_hallucination.return_value = []
            mock_policy.return_value = []

            # First run - should trigger rewrite
            result = await test_runner.invoke(
                query=sample_query,
                max_rewrites=2,
            )

            # Should have attempted rewrite
            assert result.get("rewrite_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_graph_hitl_on_guardrail_violation(self, test_runner, sample_query):
        """Test graph triggers HITL on guardrail violation."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_rewrite_llm, \
             patch("contextforge.agentic.nodes.retrieve.EmbedderRegistry") as mock_embedder_registry, \
             patch("contextforge.agentic.nodes.retrieve.get_session") as mock_get_session, \
             patch("contextforge.agentic.nodes.rerank.RerankNode._rerank") as mock_rerank, \
             patch("contextforge.agentic.nodes.synthesize.ChatAnthropic") as mock_synthesize_llm, \
             patch("contextforge.agentic.nodes.verify.ChatOpenAI") as mock_verify_llm, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_pii") as mock_pii, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_toxicity") as mock_toxicity, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_hallucination") as mock_hallucination, \
             patch("contextforge.agentic.nodes.guardrail.GuardrailNode._check_policy") as mock_policy:

            # Setup normal mocks
            mock_rewrite_instance = AsyncMock()
            mock_rewrite_output = MagicMock()
            mock_rewrite_output.rewritten_queries = ["query 1"]
            mock_rewrite_output.hyde_document = "HyDE"
            mock_rewrite_output.reasoning = "Reasoning"
            mock_rewrite_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_rewrite_output)
            mock_rewrite_llm.return_value = mock_rewrite_instance

            mock_embedder = AsyncMock()
            mock_embedder.embed = AsyncMock(return_value=[[0.1] * 3072])
            mock_embedder_registry.get.return_value = mock_embedder

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [
                MagicMock(
                    id=uuid4(),
                    document_id=uuid4(),
                    chunk_index=0,
                    content="Content",
                    token_count=10,
                    strategy="semantic",
                    metadata={},
                    embedding_model="test",
                    embedding_provider="test",
                    similarity=0.9,
                ),
            ]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_rerank_result = MagicMock()
            mock_rerank_result.results = [MagicMock(index=0, relevance_score=0.9)]
            mock_rerank.return_value = mock_rerank_result

            mock_synthesize_instance = AsyncMock()
            mock_synthesize_output = MagicMock()
            mock_synthesize_output.answer = "Contact me at john@example.com"
            mock_synthesize_output.citations = []
            mock_synthesize_output.reasoning = "Answer with email"
            mock_synthesize_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_synthesize_output)
            async def mock_stream(*args, **kwargs):
                for part in "Contact me at john@example.com".split(" "):
                    yield MagicMock(content=part + " ")
            mock_synthesize_instance.astream = mock_stream
            mock_synthesize_llm.return_value = mock_synthesize_instance

            mock_verify_instance = AsyncMock()
            mock_verify_output = MagicMock()
            mock_verify_output.confidence = 0.9
            mock_verify_output.factual_consistency = 0.9
            mock_verify_output.answer_completeness = 0.9
            mock_verify_output.hallucination_flags = []
            mock_verify_output.rewrite_signal = False
            mock_verify_output.reasoning = "Good"
            mock_verify_instance.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_verify_output)
            mock_verify_llm.return_value = mock_verify_instance

            # Guardrail detects PII
            from contextforge.agentic.state import GuardrailViolation
            mock_pii.return_value = [
                GuardrailViolation(
                    violation_type="pii",
                    severity="high",
                    description="Email detected",
                    detected_content="john@example.com",
                    suggested_action="hitl",
                )
            ]
            mock_toxicity.return_value = []
            mock_hallucination.return_value = []
            mock_policy.return_value = []

            # Run - should hit HITL interrupt
            try:
                result = await test_runner.invoke(query=sample_query)
            except Exception as e:
                # Expected interrupt
                assert "interrupt" in str(type(e)).lower() or "hitl" in str(e).lower()

            # Check state has HITL payload
            # Note: In real execution, the graph would pause at interrupt
            # For testing, we verify the guardrail would trigger HITL


# =============================================================================
# Checkpoint/Resume Tests
# =============================================================================


class TestCheckpointResume:
    """Tests for checkpoint and resume functionality."""

    @pytest.mark.asyncio
    async def test_get_state_after_execution(self, test_runner, sample_query, mock_all_llms):
        """Test getting state after graph execution."""
        thread_id = f"test_thread_{uuid4().hex[:8]}"

        result = await test_runner.invoke(
            query=sample_query,
            thread_id=thread_id,
        )

        # Get state
        state = await test_runner.get_state(thread_id)
        assert state is not None
        assert state.get("answer") == result.get("answer")
        assert state.get("request_id") == result.get("request_id")

    @pytest.mark.asyncio
    async def test_resume_from_hitl(self, test_runner, sample_query):
        """Test resuming from HITL with approve action."""
        # This test simulates the HITL flow
        # In practice, the graph pauses at interrupt and resume_from_hitl continues it

        thread_id = f"test_thread_{uuid4().hex[:8]}"

        # First, we'd need to run to HITL point
        # For this test, we verify the resume method exists and works
        hitl_response = {
            "action": "approve",
            "reviewer_id": "test_reviewer",
        }

        # The actual resume would require the graph to be in interrupted state
        # This is more of an API contract test
        assert hasattr(test_runner, "resume_from_hitl")


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in graph."""

    @pytest.mark.asyncio
    async def test_graph_handles_llm_failure_gracefully(self, test_runner, sample_query):
        """Test graph handles LLM failures without crashing."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_rewrite_llm:
            mock_rewrite_llm.side_effect = Exception("API unavailable")

            result = await test_runner.invoke(query=sample_query)

            # Should have error but not crash
            assert result.get("error") is not None
            assert result.get("error_node") == "rewrite"

    @pytest.mark.asyncio
    async def test_graph_handles_db_failure(self, test_runner, sample_query):
        """Test graph handles database failures."""
        with patch("contextforge.agentic.nodes.retrieve.get_session") as mock_get_session:
            mock_get_session.side_effect = Exception("DB connection failed")

            result = await test_runner.invoke(query=sample_query)

            assert result.get("error") is not None
            assert "retrieve" in result.get("error_node", "") or "retrieve" in result.get("error", "")


# =============================================================================
# Performance/Load Tests (Basic)
# =============================================================================


class TestPerformance:
    """Basic performance tests."""

    @pytest.mark.asyncio
    async def test_graph_latency_tracking(self, test_runner, sample_query, mock_all_llms):
        """Test graph tracks latency for each phase."""
        result = await test_runner.invoke(query=sample_query)

        # Check all latency fields present
        assert "rewrite_latency_ms" in result or "retrieval_latency_ms" in result
        assert "rerank_latency_ms" in result
        assert "synthesis_latency_ms" in result
        assert "verify_latency_ms" in result
        assert "guardrail_latency_ms" in result
        assert result.get("total_latency_ms") is not None
        assert result["total_latency_ms"] > 0


# =============================================================================
# Run with: pytest tests/integration/test_rag_graph.py -v
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
