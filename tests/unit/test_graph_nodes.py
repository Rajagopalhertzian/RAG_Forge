"""
ContextForge Unit Tests - Graph Nodes

Unit tests for each node in the agentic RAG graph.
Run with: pytest tests/unit/test_graph_nodes.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from contextforge.agentic.nodes.guardrail import GuardrailNode
from contextforge.agentic.nodes.hitl import HITLNode
from contextforge.agentic.nodes.rerank import RerankNode
from contextforge.agentic.nodes.retrieve import RetrieveNode
from contextforge.agentic.nodes.rewrite import RewriteNode, rewrite_node
from contextforge.agentic.nodes.synthesize import SynthesizeNode
from contextforge.agentic.nodes.verify import VerifyNode
from contextforge.agentic.state import (
    Chunk,
    Citation,
    GuardrailViolation,
    RAGState,
    VerificationResult,
    create_initial_state,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_state() -> RAGState:
    """Create a sample state for testing."""
    return create_initial_state(
        query="How do I configure pgvector HNSW index?",
        session_id="test_session",
        user_id="test_user",
        top_k=10,
        retrieval_k=100,
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Create sample chunks for testing."""
    return [
        Chunk(
            id=uuid4(),
            document_id=uuid4(),
            content="To configure pgvector HNSW index, use CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
            token_count=45,
            score=0.95,
            metadata={"source_type": "documentation"},
        ),
        Chunk(
            id=uuid4(),
            document_id=uuid4(),
            content="HNSW parameters: M=16 controls graph connectivity, ef_construction=64 controls build-time accuracy",
            token_count=30,
            score=0.87,
            metadata={"source_type": "documentation"},
        ),
    ]


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI response for rewrite node."""
    mock = MagicMock()
    mock.rewritten_queries = [
        "pgvector HNSW index configuration",
        "How to create HNSW index in pgvector",
        "pgvector vector_cosine_ops HNSW parameters",
    ]
    mock.hyde_document = "This document explains how to configure pgvector HNSW index with optimal parameters for vector similarity search."
    mock.reasoning = "Generated diverse queries covering configuration, creation, and parameters"
    return mock


@pytest.fixture
def mock_anthropic_response():
    """Mock Anthropic response for synthesize node."""
    mock = MagicMock()
    mock.answer = "To configure pgvector HNSW index, use CREATE INDEX with vector_cosine_ops [chunk_id_1]. Key parameters are M=16 and ef_construction=64 [chunk_id_2]."
    mock.citations = [
        Citation(
            claim="Use CREATE INDEX with vector_cosine_ops",
            chunk_ids=[uuid4(), uuid4()],
            chunk_scores=[0.95, 0.87],
        )
    ]
    mock.reasoning = "Answer directly addresses query with citations"
    return mock


@pytest.fixture
def mock_verification_result():
    """Mock verification result."""
    return VerificationResult(
        confidence=0.85,
        hallucination_flags=[],
        rewrite_signal=False,
        reasoning="Answer is well-grounded in context",
        factual_consistency=0.9,
        answer_completeness=0.8,
    )


# =============================================================================
# Rewrite Node Tests
# =============================================================================


class TestRewriteNode:
    """Tests for rewrite node."""

    @pytest.mark.asyncio
    async def test_rewrite_node_success(self, sample_state, mock_openai_response):
        """Test successful rewrite with mocked LLM."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_openai_response)
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            node = RewriteNode()
            result = await node(sample_state)

        assert result["rewritten_queries"] == mock_openai_response.rewritten_queries
        assert result["hyde_document"] == mock_openai_response.hyde_document
        assert result["rewrite_count"] == 1
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_rewrite_node_error_handling(self, sample_state):
        """Test rewrite node handles LLM errors gracefully."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_structured_llm.ainvoke = AsyncMock(side_effect=Exception("API Error"))
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            node = RewriteNode()
            result = await node(sample_state)

        assert result.get("error") is not None
        assert result["error_node"] == "rewrite"
        assert "Rewrite failed" in result["error"]

    @pytest.mark.asyncio
    async def test_rewrite_node_streaming_events(self, sample_state, mock_openai_response):
        """Test rewrite node emits streaming events."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_openai_response)
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            node = RewriteNode()
            result = await node(sample_state)

        assert "stream_events" in result
        events = result["stream_events"]
        assert any(e["type"] == "phase_start" for e in events)
        assert any(e["type"] == "phase_complete" for e in events)


# =============================================================================
# Retrieve Node Tests
# =============================================================================


class TestRetrieveNode:
    """Tests for retrieve node."""

    @pytest.mark.asyncio
    async def test_retrieve_node_empty_queries(self, sample_state):
        """Test retrieve with no queries."""
        sample_state["rewritten_queries"] = []
        sample_state["query"] = "test query"

        with patch("contextforge.agentic.nodes.retrieve.get_session") as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()

            node = RetrieveNode()
            result = await node(sample_state)

        # Should still work with original query
        assert "retrieved_chunks" in result
        assert isinstance(result["retrieved_chunks"], list)

    @pytest.mark.asyncio
    async def test_retrieve_node_rrf_fusion(self, sample_state):
        """Test RRF fusion logic."""
        node = RetrieveNode()

        # Create mock vector and BM25 results
        chunk_id_1 = uuid4()
        chunk_id_2 = uuid4()

        vector_chunks = [
            Chunk(id=chunk_id_1, document_id=uuid4(), content="vec1", token_count=10, score=0.9),
            Chunk(id=chunk_id_2, document_id=uuid4(), content="vec2", token_count=10, score=0.8),
        ]

        bm25_chunks = [
            Chunk(id=chunk_id_2, document_id=uuid4(), content="bm25_2", token_count=10, score=0.95),
            Chunk(id=uuid4(), document_id=uuid4(), content="bm25_3", token_count=10, score=0.7),
        ]

        fused = node._rrf_fuse(vector_chunks, bm25_chunks)

        # chunk_id_2 appears in both, should have highest RRF score
        assert len(fused) == 3
        top_chunk = max(fused, key=lambda c: c.score)
        assert top_chunk.id == chunk_id_2


# =============================================================================
# Rerank Node Tests
# =============================================================================


class TestRerankNode:
    """Tests for rerank node."""

    @pytest.mark.asyncio
    async def test_rerank_node_empty_input(self, sample_state):
        """Test rerank with empty chunks."""
        sample_state["retrieved_chunks"] = []

        node = RerankNode()
        result = await node(sample_state)

        assert result["reranked_chunks"] == []
        assert result["rerank_latency_ms"] == 0

    @pytest.mark.asyncio
    async def test_rerank_node_fallback_on_error(self, sample_state, sample_chunks):
        """Test rerank falls back to original chunks on error."""
        sample_state["retrieved_chunks"] = sample_chunks

        with patch("contextforge.agentic.nodes.rerank.RerankNode._rerank") as mock_rerank:
            mock_rerank.side_effect = Exception("Bedrock unavailable")

            node = RerankNode()
            result = await node(sample_state)

        # Should fallback to original chunks
        assert len(result["reranked_chunks"]) == len(sample_chunks)
        assert all(c.rerank_score == c.score for c in result["reranked_chunks"])


# =============================================================================
# Synthesize Node Tests
# =============================================================================


class TestSynthesizeNode:
    """Tests for synthesize node."""

    @pytest.mark.asyncio
    async def test_synthesize_node_empty_chunks(self, sample_state):
        """Test synthesize with no chunks."""
        sample_state["reranked_chunks"] = []

        node = SynthesizeNode(streaming=False)
        result = await node(sample_state)

        assert "No relevant documents found" in result["answer"]
        assert result["citations"] == []

    @pytest.mark.asyncio
    async def test_synthesize_node_citation_extraction(self, sample_state, sample_chunks):
        """Test citation extraction from answer."""
        sample_state["reranked_chunks"] = sample_chunks
        chunk_ids = [str(c.id) for c in sample_chunks]

        with patch("contextforge.agentic.nodes.synthesize.ChatAnthropic") as mock_llm_class:
            mock_llm = AsyncMock()
            # Mock streaming - astream should be an async generator
            async def mock_astream(*args, **kwargs):
                for part in ["Answer ", "with ", "citation ", f"[{chunk_ids[0]}]", " and ", "another ", f"[{chunk_ids[1]}]."]:
                    yield MagicMock(content=part)

            mock_llm.astream = mock_astream
            mock_llm_class.return_value = mock_llm

            node = SynthesizeNode(streaming=True)
            result = await node(sample_state)

        assert len(result["citations"]) > 0
        # Citations should reference the chunk IDs
        all_cited_ids = set()
        for c in result["citations"]:
            all_cited_ids.update(str(cid) for cid in c.chunk_ids)
        assert chunk_ids[0] in all_cited_ids or chunk_ids[1] in all_cited_ids


# =============================================================================
# Verify Node Tests
# =============================================================================


class TestVerifyNode:
    """Tests for verify node."""

    @pytest.mark.asyncio
    async def test_verify_node_high_confidence_no_rewrite(self, sample_state, sample_chunks, mock_verification_result):
        """Test verify with high confidence - no rewrite signal."""
        sample_state["answer"] = "Well-grounded answer"
        sample_state["reranked_chunks"] = sample_chunks
        sample_state["citations"] = [Citation(claim="test", chunk_ids=[c.id for c in sample_chunks], chunk_scores=[0.9, 0.8])]

        with patch("contextforge.agentic.nodes.verify.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_output = MagicMock()
            mock_output.confidence = 0.9
            mock_output.factual_consistency = 0.95
            mock_output.answer_completeness = 0.9
            mock_output.hallucination_flags = []
            mock_output.rewrite_signal = False
            mock_output.reasoning = "High quality answer"
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_output)
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            node = VerifyNode()
            result = await node(sample_state)

        verification = result["verification"]
        assert verification.confidence >= 0.7
        assert verification.rewrite_signal is False

    @pytest.mark.asyncio
    async def test_verify_node_low_confidence_triggers_rewrite(self, sample_state, sample_chunks):
        """Test verify with low confidence triggers rewrite."""
        sample_state["answer"] = "Poor answer"
        sample_state["reranked_chunks"] = sample_chunks
        sample_state["citations"] = []

        with patch("contextforge.agentic.nodes.verify.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_output = MagicMock()
            mock_output.confidence = 0.4
            mock_output.factual_consistency = 0.5
            mock_output.answer_completeness = 0.4
            mock_output.hallucination_flags = ["Unsupported claim"]
            mock_output.rewrite_signal = True
            mock_output.reasoning = "Low confidence"
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_output)
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            node = VerifyNode()
            result = await node(sample_state)

        verification = result["verification"]
        assert verification.rewrite_signal is True
        assert len(verification.hallucination_flags) > 0


# =============================================================================
# Guardrail Node Tests
# =============================================================================


class TestGuardrailNode:
    """Tests for guardrail node."""

    @pytest.mark.asyncio
    async def test_guardrail_pii_detection(self, sample_state, sample_chunks):
        """Test PII detection in guardrail."""
        sample_state["answer"] = "Contact me at john.doe@example.com for details"
        sample_state["reranked_chunks"] = sample_chunks

        node = GuardrailNode(enable_presidio=False)  # Use regex fallback
        result = await node(sample_state)

        assert len(result["guardrail_violations"]) > 0
        pii_violations = [v for v in result["guardrail_violations"] if v.violation_type == "pii"]
        assert len(pii_violations) > 0
        assert result["guardrail_action"] in ["hitl", "block", "rewrite"]

    @pytest.mark.asyncio
    async def test_guardrail_toxicity_detection(self, sample_state, sample_chunks):
        """Test toxicity detection."""
        sample_state["answer"] = "This content contains hate speech and is harmful"
        sample_state["reranked_chunks"] = sample_chunks

        node = GuardrailNode()
        result = await node(sample_state)

        toxicity_violations = [v for v in result["guardrail_violations"] if v.violation_type == "toxicity"]
        assert len(toxicity_violations) > 0

    @pytest.mark.asyncio
    async def test_guardrail_clean_content(self, sample_state, sample_chunks):
        """Test guardrail passes clean content."""
        sample_state["answer"] = "This is a clean, helpful answer about pgvector configuration."
        sample_state["reranked_chunks"] = sample_chunks

        node = GuardrailNode()
        result = await node(sample_state)

        assert result["guardrail_action"] == "proceed"
        assert len(result["guardrail_violations"]) == 0


# =============================================================================
# HITL Node Tests
# =============================================================================


class TestHITLNode:
    """Tests for HITL node."""

    @pytest.mark.asyncio
    async def test_hitl_skipped_when_not_required(self, sample_state):
        """Test HITL node passes through when not required."""
        sample_state["hitl_required"] = False

        node = HITLNode()
        result = await node(sample_state)

        assert result.get("hitl_required") is False
        # Should not have hitl_payload

    @pytest.mark.asyncio
    async def test_hitl_initiate_creates_payload(self, sample_state, sample_chunks):
        """Test HITL creates payload when required."""
        sample_state["hitl_required"] = True
        sample_state["answer"] = "Test answer"
        sample_state["citations"] = []
        sample_state["guardrail_violations"] = [
            GuardrailViolation(
                violation_type="pii",
                severity="high",
                description="PII detected",
                suggested_action="hitl",
            )
        ]
        sample_state["guardrail_action"] = "hitl"

        node = HITLNode()

        # Should raise interrupt (we catch it)
        try:
            result = await node(sample_state)
        except Exception:
            pass  # Expected interrupt

        # Check payload was created
        assert "hitl_payload" in sample_state
        assert sample_state["hitl_payload"]["query"] == sample_state["query"]
        assert sample_state["graph_checkpoint_id"] is not None

    @pytest.mark.asyncio
    async def test_hitl_process_approve(self, sample_state):
        """Test HITL processes approve response."""
        sample_state["hitl_required"] = True
        sample_state["hitl_response"] = {
            "action": "approve",
            "reviewer_id": "reviewer_1",
        }

        node = HITLNode()
        result = await node(sample_state)

        assert result["hitl_required"] is False
        assert result["guardrail_action"] == "proceed"

    @pytest.mark.asyncio
    async def test_hitl_process_modify(self, sample_state):
        """Test HITL processes modify response."""
        sample_state["hitl_required"] = True
        sample_state["hitl_response"] = {
            "action": "modify",
            "modified_answer": "Modified answer",
            "reviewer_id": "reviewer_1",
        }

        node = HITLNode()
        result = await node(sample_state)

        assert result["answer"] == "Modified answer"
        assert result["guardrail_action"] == "proceed"

    @pytest.mark.asyncio
    async def test_hitl_process_reject(self, sample_state):
        """Test HITL processes reject response."""
        sample_state["hitl_required"] = True
        sample_state["hitl_response"] = {
            "action": "reject",
            "reviewer_notes": "Answer needs more detail",
            "reviewer_id": "reviewer_1",
        }

        node = HITLNode()
        result = await node(sample_state)

        assert result["guardrail_action"] == "rewrite"


# =============================================================================
# State Helpers Tests
# =============================================================================


class TestStateHelpers:
    """Tests for state helper functions."""

    def test_create_initial_state(self):
        """Test initial state creation."""
        state = create_initial_state(
            query="test query",
            session_id="sess_1",
            user_id="user_1",
        )

        assert state["query"] == "test query"
        assert state["session_id"] == "sess_1"
        assert state["user_id"] == "user_1"
        assert state["current_phase"] == "rewrite"
        assert state["rewrite_count"] == 0
        assert state["request_id"] is not None
        assert state["started_at"] is not None

    def test_update_phase(self, sample_state):
        """Test phase update."""
        updated = sample_state.copy()
        updated["current_phase"] = "retrieve"
        updated["phase_progress"] = {"test": "data"}

        # Use the helper
        from contextforge.agentic.state import update_phase
        result = update_phase(updated, "rerank", custom="value")

        assert result["current_phase"] == "rerank"
        assert result["phase_progress"]["custom"] == "value"

    def test_add_stream_event(self, sample_state):
        """Test adding stream event."""
        from contextforge.agentic.state import add_stream_event

        result = add_stream_event(sample_state, "token", {"token": "hello"})

        assert len(result["stream_events"]) == 1
        assert result["stream_events"][0]["type"] == "token"
        assert result["stream_events"][0]["data"]["token"] == "hello"


# =============================================================================
# Integration Test: Full Node Chain
# =============================================================================


class TestNodeChain:
    """Test nodes work together in sequence."""

    @pytest.mark.asyncio
    async def test_rewrite_to_retrieve_flow(self, sample_state, mock_openai_response):
        """Test flow from rewrite to retrieve."""
        with patch("contextforge.agentic.nodes.rewrite.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_structured_llm = Mock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_openai_response)
            mock_llm.with_structured_output = Mock(return_value=mock_structured_llm)
            mock_llm_class.return_value = mock_llm

            # Run rewrite
            rewrite_result = await rewrite_node(sample_state)

        assert "rewritten_queries" in rewrite_result
        assert len(rewrite_result["rewritten_queries"]) > 0

        # Verify retrieve can use rewritten queries
        assert rewrite_result["rewritten_queries"] == mock_openai_response.rewritten_queries


# =============================================================================
# Run with: pytest tests/unit/test_graph_nodes.py -v
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
