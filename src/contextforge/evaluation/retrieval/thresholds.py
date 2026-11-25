"""
Threshold Configuration and Regression Alerting

Defines evaluation gates, alerting rules, and regression detection for CI/CD integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class AlertLevel(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class GateStatus(Enum):
    """Gate evaluation status."""

    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class ThresholdRule:
    """A single threshold rule for a metric."""

    metric: str  # e.g., "mrr_at_10", "latency_p95"
    operator: str  # ">=", "<=", ">", "<", "=="
    threshold: float
    description: str = ""
    alert_level: AlertLevel = AlertLevel.CRITICAL

    def evaluate(self, value: float) -> bool:
        """Evaluate if value passes threshold."""
        if self.operator == ">=":
            return value >= self.threshold
        elif self.operator == "<=":
            return value <= self.threshold
        elif self.operator == ">":
            return value > self.threshold
        elif self.operator == "<":
            return value < self.threshold
        elif self.operator == "==":
            return value == self.threshold
        else:
            raise ValueError(f"Unknown operator: {self.operator}")

    def get_status(self, value: float) -> GateStatus:
        """Get gate status for value."""
        if self.evaluate(value):
            return GateStatus.PASSED
        elif self.alert_level == AlertLevel.WARNING:
            return GateStatus.WARNING
        else:
            return GateStatus.FAILED


@dataclass
class GateConfig:
    """Configuration for evaluation gates."""

    # Retrieval gates
    retrieval_rules: list[ThresholdRule] = field(default_factory=list)

    # Generation gates
    generation_rules: list[ThresholdRule] = field(default_factory=list)

    # Custom gates
    custom_rules: list[ThresholdRule] = field(default_factory=list)

    def __post_init__(self):
        if not self.retrieval_rules:
            self.retrieval_rules = self._default_retrieval_rules()
        if not self.generation_rules:
            self.generation_rules = self._default_generation_rules()

    @staticmethod
    def _default_retrieval_rules() -> list[ThresholdRule]:
        """Default retrieval evaluation gates."""
        return [
            ThresholdRule(
                metric="mrr_at_10",
                operator=">=",
                threshold=0.65,
                description="Mean Reciprocal Rank at 10 must be at least 0.65",
                alert_level=AlertLevel.CRITICAL,
            ),
            ThresholdRule(
                metric="ndcg_at_10",
                operator=">=",
                threshold=0.70,
                description="NDCG at 10 must be at least 0.70",
                alert_level=AlertLevel.WARNING,
            ),
            ThresholdRule(
                metric="recall_at_10",
                operator=">=",
                threshold=0.80,
                description="Recall at 10 must be at least 0.80",
                alert_level=AlertLevel.WARNING,
            ),
            ThresholdRule(
                metric="latency_p95",
                operator="<=",
                threshold=800.0,
                description="P95 retrieval latency must not exceed 800ms",
                alert_level=AlertLevel.CRITICAL,
            ),
            ThresholdRule(
                metric="latency_p99",
                operator="<=",
                threshold=1500.0,
                description="P99 retrieval latency must not exceed 1500ms",
                alert_level=AlertLevel.WARNING,
            ),
        ]

    @staticmethod
    def _default_generation_rules() -> list[ThresholdRule]:
        """Default generation evaluation gates (RAGAS + custom)."""
        return [
            ThresholdRule(
                metric="faithfulness",
                operator=">=",
                threshold=0.85,
                description="RAGAS Faithfulness must be at least 0.85",
                alert_level=AlertLevel.CRITICAL,
            ),
            ThresholdRule(
                metric="answer_relevancy",
                operator=">=",
                threshold=0.80,
                description="RAGAS Answer Relevancy must be at least 0.80",
                alert_level=AlertLevel.CRITICAL,
            ),
            ThresholdRule(
                metric="context_precision",
                operator=">=",
                threshold=0.75,
                description="RAGAS Context Precision must be at least 0.75",
                alert_level=AlertLevel.WARNING,
            ),
            ThresholdRule(
                metric="context_recall",
                operator=">=",
                threshold=0.75,
                description="RAGAS Context Recall must be at least 0.75",
                alert_level=AlertLevel.WARNING,
            ),
            ThresholdRule(
                metric="hallucination_rate",
                operator="<=",
                threshold=0.05,
                description="Hallucination rate must not exceed 5%",
                alert_level=AlertLevel.CRITICAL,
            ),
            ThresholdRule(
                metric="citation_accuracy",
                operator=">=",
                threshold=0.95,
                description="Citation accuracy must be at least 95%",
                alert_level=AlertLevel.CRITICAL,
            ),
        ]

    def get_all_rules(self) -> list[ThresholdRule]:
        """Get all rules combined."""
        return self.retrieval_rules + self.generation_rules + self.custom_rules

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "retrieval_rules": [
                {
                    "metric": r.metric,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "description": r.description,
                    "alert_level": r.alert_level.value,
                }
                for r in self.retrieval_rules
            ],
            "generation_rules": [
                {
                    "metric": r.metric,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "description": r.description,
                    "alert_level": r.alert_level.value,
                }
                for r in self.generation_rules
            ],
            "custom_rules": [
                {
                    "metric": r.metric,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "description": r.description,
                    "alert_level": r.alert_level.value,
                }
                for r in self.custom_rules
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateConfig:
        """Create from dictionary."""
        config = cls()
        config.retrieval_rules = [
            ThresholdRule(
                metric=r["metric"],
                operator=r["operator"],
                threshold=r["threshold"],
                description=r.get("description", ""),
                alert_level=AlertLevel(r.get("alert_level", "critical")),
            )
            for r in data.get("retrieval_rules", [])
        ]
        config.generation_rules = [
            ThresholdRule(
                metric=r["metric"],
                operator=r["operator"],
                threshold=r["threshold"],
                description=r.get("description", ""),
                alert_level=AlertLevel(r.get("alert_level", "critical")),
            )
            for r in data.get("generation_rules", [])
        ]
        config.custom_rules = [
            ThresholdRule(
                metric=r["metric"],
                operator=r["operator"],
                threshold=r["threshold"],
                description=r.get("description", ""),
                alert_level=AlertLevel(r.get("alert_level", "critical")),
            )
            for r in data.get("custom_rules", [])
        ]
        return config


@dataclass
class GateResult:
    """Result of evaluating a single gate."""

    rule: ThresholdRule
    actual_value: float
    status: GateStatus
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "metric": self.rule.metric,
            "operator": self.rule.operator,
            "threshold": self.rule.threshold,
            "actual_value": self.actual_value,
            "status": self.status.value,
            "description": self.rule.description,
            "alert_level": self.rule.alert_level.value,
            "timestamp": self.timestamp,
        }


class GateEvaluator:
    """Evaluates metrics against configured gates."""

    def __init__(self, config: GateConfig = None):
        self.config = config or GateConfig()

    def evaluate(self, metrics: dict[str, float]) -> list[GateResult]:
        """
        Evaluate all gates against provided metrics.

        Args:
            metrics: Dictionary of metric_name -> value

        Returns:
            List of GateResult for each rule
        """
        results = []
        for rule in self.config.get_all_rules():
            value = metrics.get(rule.metric)
            if value is None:
                # Metric not provided - treat as failure for critical, warning for warning
                status = GateStatus.FAILED if rule.alert_level == AlertLevel.CRITICAL else GateStatus.WARNING
                results.append(GateResult(
                    rule=rule,
                    actual_value=float("nan"),
                    status=status,
                ))
                continue

            status = rule.get_status(value)
            results.append(GateResult(
                rule=rule,
                actual_value=value,
                status=status,
            ))

        return results

    def overall_status(self, results: list[GateResult]) -> GateStatus:
        """Determine overall gate status."""
        if any(r.status == GateStatus.FAILED for r in results):
            return GateStatus.FAILED
        if any(r.status == GateStatus.WARNING for r in results):
            return GateStatus.WARNING
        return GateStatus.PASSED


@dataclass
class RegressionAlert:
    """Alert for metric regression detection."""

    metric: str
    current_value: float
    baseline_value: float
    change_percent: float
    threshold_percent: float
    severity: AlertLevel
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class RegressionDetector:
    """
    Detects metric regressions by comparing current values against baseline.
    """

    def __init__(self, regression_threshold_percent: float = 5.0):
        """
        Initialize detector.

        Args:
            regression_threshold_percent: Minimum % change to trigger alert (default: 5%)
        """
        self.regression_threshold_percent = regression_threshold_percent
        self.baselines: dict[str, float] = {}

    def set_baseline(self, metric: str, value: float) -> None:
        """Set baseline value for a metric."""
        self.baselines[metric] = value

    def load_baselines(self, path: Path) -> None:
        """Load baselines from JSON file."""
        if path.exists():
            with open(path) as f:
                self.baselines = json.load(f)

    def save_baselines(self, path: Path) -> None:
        """Save baselines to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.baselines, f, indent=2)

    def check_regression(self, metrics: dict[str, float]) -> list[RegressionAlert]:
        """
        Check for regressions against baselines.

        Args:
            metrics: Current metric values

        Returns:
            List of RegressionAlert for detected regressions
        """
        alerts = []
        for metric, current_value in metrics.items():
            baseline = self.baselines.get(metric)
            if baseline is None:
                continue

            if baseline == 0:
                change_percent = 0.0 if current_value == 0 else float("inf")
            else:
                change_percent = ((current_value - baseline) / baseline) * 100

            # Check if regression (negative change for "higher is better" metrics)
            # For latency metrics, positive change is regression
            is_latency = "latency" in metric.lower()
            is_regression = (
                (is_latency and change_percent > self.regression_threshold_percent) or
                (not is_latency and change_percent < -self.regression_threshold_percent)
            )

            if is_regression:
                severity = AlertLevel.CRITICAL if abs(change_percent) > 2 * self.regression_threshold_percent else AlertLevel.WARNING
                alerts.append(RegressionAlert(
                    metric=metric,
                    current_value=current_value,
                    baseline_value=baseline,
                    change_percent=change_percent,
                    threshold_percent=self.regression_threshold_percent,
                    severity=severity,
                    message=f"{metric} regressed by {abs(change_percent):.1f}% "
                            f"(baseline: {baseline:.4f}, current: {current_value:.4f})",
                ))

        return alerts


def create_default_gate_config() -> GateConfig:
    """Create default gate configuration."""
    return GateConfig()


def create_ci_gate_config() -> GateConfig:
    """Create strict CI gate configuration (blocks merge on failure)."""
    config = GateConfig()
    # CI uses only critical rules
    config.retrieval_rules = [r for r in config.retrieval_rules if r.alert_level == AlertLevel.CRITICAL]
    config.generation_rules = [r for r in config.generation_rules if r.alert_level == AlertLevel.CRITICAL]
    return config


def create_nightly_gate_config() -> GateConfig:
    """Create nightly evaluation configuration (includes warnings)."""
    return GateConfig()  # All rules including warnings
