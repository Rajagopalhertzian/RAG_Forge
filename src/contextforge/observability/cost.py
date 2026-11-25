"""
Cost Tracking and Budget Management

Provides token accounting middleware, daily budgets, and burn alerts:
- Per-request token extraction from response headers
- USD cost calculation per model
- Daily budget tracking with 80% burn alerts
- 100% budget exhaustion → request rejection (configurable)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field

# Model pricing (USD per 1M tokens) - Update as needed
MODEL_PRICING = {
    # OpenAI
    "gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-4": {"prompt": 30.00, "completion": 60.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    "text-embedding-3-large": {"prompt": 0.13, "completion": 0.0},
    "text-embedding-3-small": {"prompt": 0.02, "completion": 0.0},
    "text-embedding-ada-002": {"prompt": 0.10, "completion": 0.0},

    # Anthropic
    "claude-3-5-sonnet-20241022": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku-20240307": {"prompt": 0.25, "completion": 1.25},
    "claude-3-opus-20240229": {"prompt": 15.00, "completion": 75.00},

    # AWS Bedrock
    "amazon.titan-embed-text-v2:0": {"prompt": 0.02, "completion": 0.0},
    "anthropic.claude-3-sonnet-20240229-v1:0": {"prompt": 3.00, "completion": 15.00},
    "anthropic.claude-3-haiku-20240307-v1:0": {"prompt": 0.25, "completion": 1.25},

    # Default fallback
    "default": {"prompt": 1.00, "completion": 2.00},
}


class CostConfig(BaseModel):
    """Configuration for cost tracking."""

    # Daily budget in USD
    daily_budget_usd: float = Field(default=100.0, ge=0)

    # Alert threshold (0-1)
    alert_threshold: float = Field(default=0.80, ge=0, le=1)

    # Reject requests when budget exhausted
    reject_on_exhausted: bool = Field(default=True)

    # Pricing overrides
    custom_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)

    # Alert webhook (Slack, etc.)
    alert_webhook: str | None = Field(default=None)

    # Track per-user budgets
    per_user_budget_usd: float | None = Field(default=None, ge=0)


@dataclass
class TokenUsage:
    """Token usage for a single request."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    operation: str  # generation, embedding, rerank
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        """Calculate cost in USD."""
        return calculate_cost(self.model, self.prompt_tokens, self.completion_tokens, self.operation)


@dataclass
class BudgetStatus:
    """Current budget status."""

    date: date
    budget_usd: float
    spent_usd: float
    remaining_usd: float
    burn_rate: float  # 0-1
    is_alert: bool
    is_exhausted: bool
    projected_daily_spend: float


class CostTracker:
    """
    Tracks token usage and costs with budget management.

    Thread-safe for concurrent use.
    """

    def __init__(self, config: CostConfig = None):
        self.config = config or CostConfig()
        self._lock = threading.RLock()
        self._usage_log: list[TokenUsage] = []
        self._daily_spend: dict[date, float] = {}
        self._user_daily_spend: dict[str, dict[date, float]] = {}
        self._alert_fired: set[date] = set()
        self._user_alert_fired: dict[str, set[date]] = {}

        # Load pricing
        self._pricing = {**MODEL_PRICING, **self.config.custom_pricing}

    def record_usage(self, usage: TokenUsage) -> float:
        """
        Record token usage and return cost.

        Args:
            usage: TokenUsage to record

        Returns:
            Cost in USD
        """
        cost = usage.cost_usd
        today = usage.timestamp.date()

        with self._lock:
            self._usage_log.append(usage)
            self._daily_spend[today] = self._daily_spend.get(today, 0.0) + cost

            if usage.user_id and self.config.per_user_budget_usd:
                user_spend = self._user_daily_spend.setdefault(usage.user_id, {})
                user_spend[today] = user_spend.get(today, 0.0) + cost

        # Check budget alerts
        self._check_budget_alerts(today, usage.user_id)

        return cost

    def _check_budget_alerts(self, today: date, user_id: str | None = None) -> None:
        """Check and fire budget alerts."""
        budget = self.config.per_user_budget_usd if user_id else self.config.daily_budget_usd
        if budget is None:
            return

        spend = self._user_daily_spend.get(user_id, {}).get(today, 0.0) if user_id else self._daily_spend.get(today, 0.0)
        burn_rate = spend / budget if budget > 0 else 0

        # 80% alert
        if burn_rate >= self.config.alert_threshold:
            alert_key = (today, user_id) if user_id else today
            alert_set = self._user_alert_fired.setdefault(user_id, set()) if user_id else self._alert_fired

            if alert_key not in alert_set:
                alert_set.add(alert_key)
                self._fire_alert(today, spend, budget, burn_rate, user_id)

    def _fire_alert(self, today: date, spend: float, budget: float, burn_rate: float, user_id: str | None) -> None:
        """Fire budget alert."""
        message = (
            f"💰 Budget Alert: {burn_rate:.0%} of daily budget used\n"
            f"Date: {today}\n"
            f"Spent: ${spend:.2f} / ${budget:.2f}\n"
            f"Remaining: ${budget - spend:.2f}"
        )
        if user_id:
            message += f"\nUser: {user_id}"

        # Log alert
        print(f"[COST ALERT] {message}")

        # Send webhook if configured
        if self.config.alert_webhook:
            self._send_webhook(message)

    def _send_webhook(self, message: str) -> None:
        """Send alert webhook (non-blocking)."""
        import threading

        import requests

        def send():
            try:
                requests.post(
                    self.config.alert_webhook,
                    json={"text": message},
                    timeout=5,
                )
            except Exception:
                pass  # Fail silently

        threading.Thread(target=send, daemon=True).start()

    def get_budget_status(self, user_id: str | None = None, check_date: date = None) -> BudgetStatus:
        """Get current budget status."""
        check_date = check_date or date.today()
        budget = self.config.per_user_budget_usd if user_id else self.config.daily_budget_usd

        if budget is None:
            return BudgetStatus(
                date=check_date,
                budget_usd=0,
                spent_usd=0,
                remaining_usd=0,
                burn_rate=0,
                is_alert=False,
                is_exhausted=False,
                projected_daily_spend=0,
            )

        with self._lock:
            if user_id:
                spend = self._user_daily_spend.get(user_id, {}).get(check_date, 0.0)
            else:
                spend = self._daily_spend.get(check_date, 0.0)

        remaining = max(0, budget - spend)
        burn_rate = spend / budget if budget > 0 else 0
        is_alert = burn_rate >= self.config.alert_threshold
        is_exhausted = spend >= budget

        # Project daily spend based on current rate
        hours_elapsed = (datetime.now() - datetime.combine(check_date, datetime.min.time())).total_seconds() / 3600
        if hours_elapsed > 0:
            projected = spend / hours_elapsed * 24
        else:
            projected = spend

        return BudgetStatus(
            date=check_date,
            budget_usd=budget,
            spent_usd=spend,
            remaining_usd=remaining,
            burn_rate=burn_rate,
            is_alert=is_alert,
            is_exhausted=is_exhausted,
            projected_daily_spend=projected,
        )

    def can_proceed(self, user_id: str | None = None, estimated_cost: float = 0.0) -> tuple[bool, str]:
        """
        Check if request can proceed within budget.

        Args:
            user_id: User ID (for per-user budgets)
            estimated_cost: Estimated cost of upcoming request

        Returns:
            Tuple of (allowed, reason)
        """
        status = self.get_budget_status(user_id)

        if status.is_exhausted:
            if self.config.reject_on_exhausted:
                return False, f"Daily budget exhausted: ${status.spent_usd:.2f} / ${status.budget_usd:.2f}"
            else:
                return True, "Budget exhausted but rejection disabled"

        # Check if estimated cost would exceed budget
        if status.remaining_usd < estimated_cost:
            if self.config.reject_on_exhausted:
                return False, f"Estimated cost ${estimated_cost:.4f} exceeds remaining budget ${status.remaining_usd:.2f}"

        return True, "OK"

    def get_usage_summary(
        self,
        start_date: date = None,
        end_date: date = None,
        user_id: str = None,
    ) -> dict[str, Any]:
        """Get usage summary for date range."""
        start_date = start_date or (date.today() - timedelta(days=30))
        end_date = end_date or date.today()

        with self._lock:
            filtered = [
                u for u in self._usage_log
                if start_date <= u.timestamp.date() <= end_date
                and (user_id is None or u.user_id == user_id)
            ]

        total_tokens = sum(u.total_tokens for u in filtered)
        total_cost = sum(u.cost_usd for u in filtered)
        by_model = {}
        by_operation = {}

        for u in filtered:
            by_model[u.model] = by_model.get(u.model, 0) + u.cost_usd
            by_operation[u.operation] = by_operation.get(u.operation, 0) + u.cost_usd

        return {
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "total_requests": len(filtered),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
            "by_operation": {k: round(v, 4) for k, v in by_operation.items()},
        }

    def cleanup_old_logs(self, days: int = 90) -> int:
        """Remove usage logs older than specified days."""
        cutoff = date.today() - timedelta(days=days)
        with self._lock:
            original_len = len(self._usage_log)
            self._usage_log = [u for u in self._usage_log if u.timestamp.date() >= cutoff]
            return original_len - len(self._usage_log)


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    operation: str = "generation",
) -> float:
    """
    Calculate cost in USD for token usage.

    Args:
        model: Model name
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        operation: Operation type (generation, embedding, rerank)

    Returns:
        Cost in USD
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

    # For embeddings, only prompt tokens count
    if operation == "embedding":
        prompt_cost = (prompt_tokens / 1_000_000) * pricing.get("prompt", 0)
        return float(Decimal(str(prompt_cost)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

    prompt_cost = (prompt_tokens / 1_000_000) * pricing.get("prompt", 0)
    completion_cost = (completion_tokens / 1_000_000) * pricing.get("completion", 0)

    total = prompt_cost + completion_cost
    return float(Decimal(str(total)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def extract_tokens_from_response(response: Any, model: str = None) -> TokenUsage | None:
    """
    Extract token usage from various LLM response formats.

    Args:
        response: LLM response object
        model: Model name (extracted from response if not provided)

    Returns:
        TokenUsage or None if not found
    """
    # OpenAI format
    if hasattr(response, "usage"):
        usage = response.usage
        return TokenUsage(
            model=model or getattr(response, "model", "unknown"),
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
            total_tokens=getattr(usage, "total_tokens", 0),
            operation="generation",
        )

    # Dict format (OpenAI, Anthropic, etc.)
    if isinstance(response, dict):
        usage = response.get("usage") or response.get("usage_metadata")
        if usage:
            return TokenUsage(
                model=model or response.get("model", "unknown"),
                prompt_tokens=usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                completion_tokens=usage.get("completion_tokens", usage.get("output_tokens", 0)),
                total_tokens=usage.get("total_tokens", 0),
                operation="generation",
            )

    # Anthropic format
    if hasattr(response, "usage") and hasattr(response.usage, "input_tokens"):
        return TokenUsage(
            model=model or getattr(response, "model", "unknown"),
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            operation="generation",
        )

    return None


# Global cost tracker
_global_tracker: CostTracker | None = None
_tracker_lock = threading.Lock()


def get_cost_tracker(config: CostConfig = None) -> CostTracker:
    """Get or create global cost tracker."""
    global _global_tracker
    with _tracker_lock:
        if _global_tracker is None:
            _global_tracker = CostTracker(config)
        return _global_tracker


def configure_cost_tracking(
    daily_budget_usd: float = 100.0,
    alert_threshold: float = 0.80,
    reject_on_exhausted: bool = True,
    per_user_budget_usd: float = None,
    alert_webhook: str = None,
) -> CostTracker:
    """Configure global cost tracker."""
    global _global_tracker
    config = CostConfig(
        daily_budget_usd=daily_budget_usd,
        alert_threshold=alert_threshold,
        reject_on_exhausted=reject_on_exhausted,
        per_user_budget_usd=per_user_budget_usd,
        alert_webhook=alert_webhook,
    )
    with _tracker_lock:
        _global_tracker = CostTracker(config)
    return _global_tracker


# FastAPI middleware for cost tracking

class CostTrackingMiddleware:
    """
    FastAPI middleware for automatic cost tracking.

    Usage:
        app.add_middleware(CostTrackingMiddleware)
    """

    def __init__(self, app, tracker: CostTracker = None):
        self.app = app
        self.tracker = tracker or get_cost_tracker()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # This is a simplified version - in practice, you'd track costs
        # by intercepting LLM calls, not HTTP requests
        await self.app(scope, receive, send)


# Decorator for tracking LLM calls

def track_cost(
    tracker: CostTracker = None,
    operation: str = "generation",
    model_param: str = "model",
):
    """
    Decorator to track cost of LLM calls.

    Usage:
        @track_cost(operation="generation")
        async def call_llm(messages, model="gpt-4o"):
            response = await openai_client.chat.completions.create(...)
            return response
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            _tracker = tracker or get_cost_tracker()

            # Extract model from kwargs
            model = kwargs.get(model_param, "unknown")

            # Check budget before call
            # Note: estimated_cost would need to be calculated based on input
            # For now, we track after the call

            result = func(*args, **kwargs)

            # Extract tokens from response
            token_usage = extract_tokens_from_response(result, model)
            if token_usage:
                token_usage.operation = operation
                _tracker.record_usage(token_usage)

            return result

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            _tracker = tracker or get_cost_tracker()
            model = kwargs.get(model_param, "unknown")

            result = await func(*args, **kwargs)

            token_usage = extract_tokens_from_response(result, model)
            if token_usage:
                token_usage.operation = operation
                _tracker.record_usage(token_usage)

            return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


from functools import wraps
