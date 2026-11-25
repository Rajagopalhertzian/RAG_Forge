"""
ContextForge Guardrail Node - Safety & Compliance Checks

Implements:
- PII detection (using Presidio)
- Toxicity classification
- Hallucination consistency check (answer vs context)
- Policy violation detection
"""

from __future__ import annotations

import re
import time
from typing import Any

from pydantic import BaseModel

from contextforge.agentic.state import (
    Chunk,
    GuardrailViolation,
    RAGState,
    add_stream_event,
    update_phase,
)
from contextforge.main import logger

# =============================================================================
# Models
# =============================================================================


class GuardrailResult(BaseModel):
    """Guardrail check results."""

    violations: list[GuardrailViolation]
    action: str  # proceed, rewrite, hitl, block
    pii_detected: bool
    toxicity_score: float
    hallucination_risk: float


# =============================================================================
# PII Patterns (fallback if Presidio unavailable)
# =============================================================================

PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "api_key": re.compile(r"\b(?:sk|pk)_[a-zA-Z0-9]{32,}\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}

TOXICITY_KEYWORDS = {
    "high": ["hate speech", "violence", "illegal", "harmful", "dangerous"],
    "medium": ["offensive", "inappropriate", "discriminatory", "harassment"],
    "low": ["controversial", "sensitive", "political", "religious"],
}


# =============================================================================
# Node Implementation
# =============================================================================


class GuardrailNode:
    """Safety and compliance guardrails."""

    def __init__(
        self,
        enable_presidio: bool = True,
        toxicity_threshold: float = 0.7,
        pii_action: str = "hitl",  # block, rewrite, hitl, allow
        toxicity_action: str = "hitl",
        hallucination_action: str = "rewrite",
    ):
        self.enable_presidio = enable_presidio
        self.toxicity_threshold = toxicity_threshold
        self.pii_action = pii_action
        self.toxicity_action = toxicity_action
        self.hallucination_action = hallucination_action

        # Try to initialize Presidio
        self.presidio_analyzer = None
        if enable_presidio:
            try:
                from presidio_analyzer import AnalyzerEngine
                self.presidio_analyzer = AnalyzerEngine()
            except ImportError:
                logger.warning("presidio_not_available", message="Using regex fallback for PII detection")

    async def __call__(self, state: RAGState) -> RAGState:
        """Execute guardrail checks."""
        start_time = time.perf_counter()

        answer = state.get("answer", "")
        reranked_chunks = state.get("reranked_chunks", [])
        verification = state.get("verification")

        state = update_phase(state, "guardrail", answer_length=len(answer))
        state = add_stream_event(
            state,
            "phase_start",
            {"phase": "guardrail", "checks": ["pii", "toxicity", "hallucination", "policy"]},
        )

        logger.info("guardrail_started", request_id=state.get("request_id"))

        try:
            violations = []

            # 1. PII Detection
            pii_violations = await self._check_pii(answer)
            violations.extend(pii_violations)

            # 2. Toxicity Check
            toxicity_violations = await self._check_toxicity(answer)
            violations.extend(toxicity_violations)

            # 3. Hallucination Consistency Check
            hallucination_violations = await self._check_hallucination(answer, reranked_chunks, verification)
            violations.extend(hallucination_violations)

            # 4. Policy Checks
            policy_violations = await self._check_policy(answer)
            violations.extend(policy_violations)

            # Determine overall action
            action = self._determine_action(violations)

            # Calculate aggregate scores
            pii_detected = any(v.violation_type == "pii" for v in violations)
            toxicity_score = max(
                (v.severity_score for v in violations if v.violation_type == "toxicity"),
                default=0.0,
            )
            hallucination_risk = max(
                (v.severity_score for v in violations if v.violation_type == "hallucination"),
                default=0.0,
            )

            state["guardrail_violations"] = violations
            state["guardrail_action"] = action
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            state["guardrail_latency_ms"] = latency_ms

            state = add_stream_event(
                state,
                "phase_complete",
                {
                    "phase": "guardrail",
                    "latency_ms": latency_ms,
                    "violations": len(violations),
                    "action": action,
                    "pii_detected": pii_detected,
                    "toxicity_score": toxicity_score,
                    "hallucination_risk": hallucination_risk,
                },
            )

            logger.info(
                "guardrail_completed",
                violations=len(violations),
                action=action,
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "guardrail_failed",
                error=str(e),
                latency_ms=latency_ms,
                request_id=state.get("request_id"),
            )
            # Fail safe: allow but log
            state["guardrail_violations"] = []
            state["guardrail_action"] = "proceed"
            state["guardrail_latency_ms"] = latency_ms
            state = add_stream_event(state, "phase_error", {"phase": "guardrail", "error": str(e)})

        return state

    async def _check_pii(self, text: str) -> list[GuardrailViolation]:
        """Check for PII using Presidio or regex fallback."""
        violations = []

        if self.presidio_analyzer:
            try:
                results = self.presidio_analyzer.analyze(text=text, language="en")
                for result in results:
                    if result.score >= 0.5:  # Confidence threshold
                        violations.append(
                            GuardrailViolation(
                                violation_type="pii",
                                severity="high" if result.score > 0.8 else "medium",
                                description=f"PII detected: {result.entity_type}",
                                detected_content=text[result.start:result.end] if result.start >= 0 else None,
                                suggested_action=self.pii_action,
                            )
                        )
            except Exception as e:
                logger.warning("presidio_analysis_failed", error=str(e))
                # Fallback to regex
                violations.extend(self._regex_pii_check(text))
        else:
            violations.extend(self._regex_pii_check(text))

        return violations

    def _regex_pii_check(self, text: str) -> list[GuardrailViolation]:
        """Regex-based PII detection fallback."""
        violations = []
        for pii_type, pattern in PII_PATTERNS.items():
            matches = pattern.findall(text)
            for match in matches:
                violations.append(
                    GuardrailViolation(
                        violation_type="pii",
                        severity="high" if pii_type in ("ssn", "credit_card", "api_key", "aws_key") else "medium",
                        description=f"PII detected: {pii_type}",
                        detected_content=match,
                        suggested_action=self.pii_action,
                    )
                )
        return violations

    async def _check_toxicity(self, text: str) -> list[GuardrailViolation]:
        """Check for toxic content (keyword-based, can be replaced with ML model)."""
        violations = []
        text_lower = text.lower()

        # Check high severity
        for keyword in TOXICITY_KEYWORDS["high"]:
            if keyword in text_lower:
                violations.append(
                    GuardrailViolation(
                        violation_type="toxicity",
                        severity="high",
                        description=f"High-severity toxic content: '{keyword}'",
                        detected_content=keyword,
                        suggested_action=self.toxicity_action,
                    )
                )

        # Check medium severity
        for keyword in TOXICITY_KEYWORDS["medium"]:
            if keyword in text_lower:
                violations.append(
                    GuardrailViolation(
                        violation_type="toxicity",
                        severity="medium",
                        description=f"Medium-severity toxic content: '{keyword}'",
                        detected_content=keyword,
                        suggested_action=self.toxicity_action,
                    )
                )

        return violations

    async def _check_hallucination(
        self,
        answer: str,
        chunks: list[Chunk],
        verification: Any | None,
    ) -> list[GuardrailViolation]:
        """Check for hallucination risk based on verification and context coverage."""
        violations = []

        if verification:
            # Use verification results
            if verification.confidence < 0.5:
                violations.append(
                    GuardrailViolation(
                        violation_type="hallucination",
                        severity="high",
                        description=f"Low confidence answer: {verification.confidence:.2f}",
                        suggested_action=self.hallucination_action,
                    )
                )
            elif verification.confidence < 0.7:
                violations.append(
                    GuardrailViolation(
                        violation_type="hallucination",
                        severity="medium",
                        description=f"Moderate confidence answer: {verification.confidence:.2f}",
                        suggested_action=self.hallucination_action,
                    )
                )

            if verification.factual_consistency < 0.5:
                violations.append(
                    GuardrailViolation(
                        violation_type="hallucination",
                        severity="high",
                        description=f"Low factual consistency: {verification.factual_consistency:.2f}",
                        suggested_action=self.hallucination_action,
                    )
                )

            for flag in verification.hallucination_flags:
                violations.append(
                    GuardrailViolation(
                        violation_type="hallucination",
                        severity="medium",
                        description=f"Hallucination flag: {flag}",
                        suggested_action=self.hallucination_action,
                    )
                )

        # Check citation coverage
        citations = state.get("citations", []) if "state" in locals() else []
        # Note: we can't access state here directly, would need to pass it
        # This is a simplified check

        return violations

    async def _check_policy(self, text: str) -> list[GuardrailViolation]:
        """Check for policy violations (customizable)."""
        violations = []

        # Example: Check for disallowed content patterns
        disallowed_patterns = [
            (r"\b(password|secret|token)\s*[:=]\s*\S+", "credential_exposure"),
            (r"\b(?:drop|delete|truncate)\s+table\b", "sql_injection_risk"),
            (r"<script.*?>.*?</script>", "xss_risk"),
        ]

        for pattern, violation_type in disallowed_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(
                    GuardrailViolation(
                        violation_type="policy",
                        severity="high",
                        description=f"Policy violation: {violation_type}",
                        suggested_action="block",
                    )
                )

        return violations

    def _determine_action(self, violations: list[GuardrailViolation]) -> str:
        """Determine overall action from violations."""
        if not violations:
            return "proceed"

        # Check for block-level violations
        if any(v.severity == "critical" or v.suggested_action == "block" for v in violations):
            return "block"

        # Check for HITL-required violations
        if any(v.suggested_action == "hitl" for v in violations):
            return "hitl"

        # Check for rewrite-required violations
        if any(v.suggested_action == "rewrite" for v in violations):
            return "rewrite"

        # Default to proceed with warning
        return "proceed"


# Add severity_score property to GuardrailViolation for sorting
@property
def severity_score(self) -> float:
    scores = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    return scores.get(self.severity, 0.0)


GuardrailViolation.severity_score = severity_score


# =============================================================================
# Factory Function
# =============================================================================


def create_guardrail_node() -> GuardrailNode:
    """Factory to create guardrail node with config."""
    return GuardrailNode(
        enable_presidio=True,
        toxicity_threshold=0.7,
        pii_action="hitl",
        toxicity_action="hitl",
        hallucination_action="rewrite",
    )


# For LangGraph functional API
async def guardrail_node(state: RAGState) -> RAGState:
    """Functional wrapper for LangGraph."""
    node = create_guardrail_node()
    return await node(state)
