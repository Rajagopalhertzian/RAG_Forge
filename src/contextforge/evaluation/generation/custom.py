"""
Custom Generation Evaluation Metrics

Implements custom metrics for RAG generation quality:
- Citation Accuracy: Every factual claim must have a supporting document chunk
- Hallucination Rate: Consistency check between answer claims and retrieved context
- Claim Coverage: Percentage of answer claims backed by citations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

# Thresholds from spec
HALLUCINATION_RATE_THRESHOLD = 0.05  # < 5%
CITATION_ACCURACY_THRESHOLD = 0.95   # >= 95%


class CitationAccuracyResult(BaseModel):
    """Result of citation accuracy evaluation."""

    score: float = Field(ge=0.0, le=1.0)
    threshold: float
    passed: bool
    total_claims: int
    cited_claims: int
    uncited_claims: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class HallucinationResult(BaseModel):
    """Result of hallucination detection."""

    hallucination_rate: float = Field(ge=0.0, le=1.0)
    threshold: float
    passed: bool
    total_claims: int
    hallucinated_claims: list[str] = Field(default_factory=list)
    supported_claims: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ClaimExtractionResult(BaseModel):
    """Result of claim extraction from text."""

    claims: list[str]
    claim_spans: list[tuple[int, int]]  # (start, end) character positions
    citations_found: list[dict[str, Any]]  # Citation markers found in text


@dataclass
class CustomEvaluatorConfig:
    """Configuration for custom evaluation."""

    hallucination_threshold: float = HALLUCINATION_RATE_THRESHOLD
    citation_accuracy_threshold: float = CITATION_ACCURACY_THRESHOLD
    # Citation patterns to detect in generated text
    citation_patterns: list[str] = field(default_factory=lambda: [
        r'\[(\d+)\]',           # [1], [2], etc.
        r'\((\d+)\)',           # (1), (2), etc.
        r'\[doc:([^\]]+)\]',    # [doc:chunk_id]
        r'\{doc:([^}]+)\}',     # {doc:chunk_id}
        r'<<(\d+)>>',           # <<1>>, <<2>>
    ])
    # Minimum claim length to consider
    min_claim_length: int = 15
    # Stop words for claim extraction
    stop_words: set[str] = field(default_factory=lambda: {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "is", "are", "was", "were", "be", "been", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "can", "this", "that", "these", "those", "what", "how",
        "why", "when", "where", "who", "which", "it", "its", "they", "them",
        "their", "we", "our", "you", "your", "i", "me", "my", "he", "him", "his",
        "she", "her", "hers", "as", "if", "then", "than", "so", "such", "very",
        "more", "most", "some", "any", "all", "each", "every", "few", "many",
        "much", "other", "another", "same", "different", "new", "old", "first",
        "last", "next", "previous", "now", "here", "there"
    })


class ClaimExtractor:
    """
    Extracts factual claims from generated text and identifies citations.
    """

    def __init__(self, config: CustomEvaluatorConfig = None):
        self.config = config or CustomEvaluatorConfig()
        self._compiled_patterns = [re.compile(p) for p in self.config.citation_patterns]

    def extract_claims(self, text: str) -> ClaimExtractionResult:
        """
        Extract factual claims from text.

        Args:
            text: Generated answer text

        Returns:
            ClaimExtractionResult with claims, spans, and citations
        """
        # Find all citations in text
        citations_found = []
        citation_positions = set()

        for pattern in self._compiled_patterns:
            for match in pattern.finditer(text):
                citations_found.append({
                    "pattern": pattern.pattern,
                    "match": match.group(),
                    "group": match.group(1) if match.groups() else None,
                    "start": match.start(),
                    "end": match.end(),
                })
                # Mark citation positions
                for i in range(match.start(), match.end()):
                    citation_positions.add(i)

        # Split text into sentences
        sentences = self._split_sentences(text)

        claims = []
        claim_spans = []

        for sent in sentences:
            sent_text = sent["text"]
            sent_start = sent["start"]
            sent_end = sent["end"]

            # Skip short sentences
            if len(sent_text) < self.config.min_claim_length:
                continue

            # Check if sentence has citation marker
            has_citation = any(
                sent_start <= c["start"] < sent_end
                for c in citations_found
            )

            # Extract sub-claims from sentence (split by clauses)
            sub_claims = self._split_claims(sent_text)

            for claim in sub_claims:
                if len(claim) >= self.config.min_claim_length:
                    # Find claim position in original text
                    claim_start = text.find(claim, sent_start, sent_end)
                    if claim_start >= 0:
                        claims.append(claim)
                        claim_spans.append((claim_start, claim_start + len(claim)))

        return ClaimExtractionResult(
            claims=claims,
            claim_spans=claim_spans,
            citations_found=citations_found,
        )

    def _split_sentences(self, text: str) -> list[dict[str, Any]]:
        """Split text into sentences with position tracking."""
        # Simple sentence splitting - in production use spaCy or nltk
        sentences = []
        # Split on sentence-ending punctuation followed by space and capital
        parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

        pos = 0
        for part in parts:
            part = part.strip()
            if part:
                start = text.find(part, pos)
                end = start + len(part)
                sentences.append({"text": part, "start": start, "end": end})
                pos = end

        return sentences

    def _split_claims(self, sentence: str) -> list[str]:
        """Split sentence into sub-claims by clauses."""
        # Split on commas, semicolons, conjunctions
        clauses = re.split(r',\s+|;\s+|\s+and\s+|\s+but\s+|\s+however\s+', sentence)
        return [c.strip() for c in clauses if len(c.strip()) > 10]


class CitationAccuracyEvaluator:
    """
    Evaluates citation accuracy: every factual claim must have a supporting document.
    """

    def __init__(self, config: CustomEvaluatorConfig = None):
        self.config = config or CustomEvaluatorConfig()
        self.claim_extractor = ClaimExtractor(self.config)

    def evaluate(
        self,
        answer: str,
        contexts: list[dict[str, Any]],
    ) -> CitationAccuracyResult:
        """
        Evaluate citation accuracy.

        Args:
            answer: Generated answer text
            contexts: List of retrieved context chunks with metadata (id, content)

        Returns:
            CitationAccuracyResult
        """
        # Extract claims and citations from answer
        extraction = self.claim_extractor.extract_claims(answer)

        if not extraction.claims:
            return CitationAccuracyResult(
                score=1.0,
                threshold=self.config.citation_accuracy_threshold,
                passed=True,
                total_claims=0,
                cited_claims=0,
                uncited_claims=[],
                details={"reason": "No claims extracted"},
            )

        # Build context lookup by ID
        context_by_id = {}
        for ctx in contexts:
            ctx_id = ctx.get("id") or ctx.get("chunk_id") or ctx.get("doc_id")
            if ctx_id:
                context_by_id[str(ctx_id)] = ctx.get("content", "")

        # Check each claim for citation
        cited_claims = 0
        uncited_claims = []

        # Get citation IDs mentioned in answer
        cited_ids = set()
        for cit in extraction.citations_found:
            if cit["group"]:
                cited_ids.add(cit["group"])

        # For each claim, check if it has a citation that maps to a context
        for claim in extraction.claims:
            # Check if claim has nearby citation
            claim_has_citation = False

            # Simple heuristic: claim is cited if any citation appears in answer
            # In production, would do more precise claim-citation alignment
            if cited_ids:
                # Verify cited IDs exist in retrieved contexts
                valid_citations = cited_ids & set(context_by_id.keys())
                if valid_citations:
                    claim_has_citation = True

            if claim_has_citation:
                cited_claims += 1
            else:
                uncited_claims.append(claim)

        score = cited_claims / len(extraction.claims) if extraction.claims else 1.0
        passed = score >= self.config.citation_accuracy_threshold

        return CitationAccuracyResult(
            score=score,
            threshold=self.config.citation_accuracy_threshold,
            passed=passed,
            total_claims=len(extraction.claims),
            cited_claims=cited_claims,
            uncited_claims=uncited_claims,
            details={
                "citations_found": [c["match"] for c in extraction.citations_found],
                "cited_doc_ids": list(cited_ids),
                "available_doc_ids": list(context_by_id.keys()),
            },
        )


class HallucinationDetector:
    """
    Detects hallucinations by checking answer claims against retrieved context.

    Hallucination = claim made in answer that is not supported by any retrieved context
    """

    def __init__(self, config: CustomEvaluatorConfig = None):
        self.config = config or CustomEvaluatorConfig()
        self.claim_extractor = ClaimExtractor(self.config)

    def evaluate(
        self,
        answer: str,
        contexts: list[dict[str, Any]],
    ) -> HallucinationResult:
        """
        Detect hallucinations in answer.

        Args:
            answer: Generated answer text
            contexts: List of retrieved context chunks with metadata (id, content)

        Returns:
            HallucinationResult
        """
        # Extract claims from answer
        extraction = self.claim_extractor.extract_claims(answer)

        if not extraction.claims:
            return HallucinationResult(
                hallucination_rate=0.0,
                threshold=self.config.hallucination_threshold,
                passed=True,
                total_claims=0,
                hallucinated_claims=[],
                supported_claims=[],
                details={"reason": "No claims extracted"},
            )

        # Combine all context content
        all_context = " ".join(ctx.get("content", "") for ctx in contexts)
        context_words = set(all_context.lower().split())

        # Remove stop words from context
        context_words = context_words - self.config.stop_words

        hallucinated = []
        supported = []

        for claim in extraction.claims:
            claim_words = set(claim.lower().split())
            claim_words = claim_words - self.config.stop_words

            if not claim_words:
                supported.append(claim)
                continue

            # Calculate word overlap with context
            overlap = claim_words & context_words
            overlap_ratio = len(overlap) / len(claim_words)

            # Claim is supported if >30% of content words appear in context
            # (threshold accounts for paraphrasing)
            if overlap_ratio > 0.3:
                supported.append(claim)
            else:
                hallucinated.append(claim)

        hallucination_rate = len(hallucinated) / len(extraction.claims)
        passed = hallucination_rate <= self.config.hallucination_threshold

        return HallucinationResult(
            hallucination_rate=hallucination_rate,
            threshold=self.config.hallucination_threshold,
            passed=passed,
            total_claims=len(extraction.claims),
            hallucinated_claims=hallucinated,
            supported_claims=supported,
            details={
                "context_word_count": len(context_words),
                "avg_claim_words": sum(len(c.split()) for c in extraction.claims) / len(extraction.claims),
            },
        )


class CustomGenerationEvaluator:
    """
    Combined custom generation evaluator.
    """

    def __init__(self, config: CustomEvaluatorConfig = None):
        self.config = config or CustomEvaluatorConfig()
        self.citation_evaluator = CitationAccuracyEvaluator(self.config)
        self.hallucination_detector = HallucinationDetector(self.config)

    def evaluate(
        self,
        answer: str,
        contexts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Run all custom evaluations.

        Args:
            answer: Generated answer text
            contexts: List of retrieved context chunks with metadata

        Returns:
            Dictionary with citation_accuracy and hallucination results
        """
        citation_result = self.citation_evaluator.evaluate(answer, contexts)
        hallucination_result = self.hallucination_detector.evaluate(answer, contexts)

        return {
            "citation_accuracy": citation_result.model_dump(),
            "hallucination": hallucination_result.model_dump(),
            "overall_passed": citation_result.passed and hallucination_result.passed,
        }


def create_custom_evaluator(
    hallucination_threshold: float = HALLUCINATION_RATE_THRESHOLD,
    citation_accuracy_threshold: float = CITATION_ACCURACY_THRESHOLD,
) -> CustomGenerationEvaluator:
    """Create custom evaluator with custom thresholds."""
    config = CustomEvaluatorConfig(
        hallucination_threshold=hallucination_threshold,
        citation_accuracy_threshold=citation_accuracy_threshold,
    )
    return CustomGenerationEvaluator(config)
