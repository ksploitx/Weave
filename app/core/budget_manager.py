"""
BudgetManager — token-budget enforcement for multi-agent LLM calls.

Responsibilities:
  1. Check whether a proposed call fits within the remaining token budget.
  2. Record actual token usage after a successful LLM response.
  3. Trigger a fallback model when the primary model is unavailable.
  4. Provide a rough token estimate from raw text (word-count heuristic)
     before the real API count is known.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.schemas.context import SharedContext

logger = logging.getLogger(__name__)

# Conservative chars-per-token ratio used for pre-call estimation.
# Real tokenisers vary; this keeps us safely under budget.
_CHARS_PER_TOKEN: float = 4.0


class BudgetExceededError(Exception):
    """Raised when a proposed LLM call would exceed the job's token budget."""

    def __init__(self, requested: int, remaining: int) -> None:
        self.requested = requested
        self.remaining = remaining
        super().__init__(
            f"Token budget exceeded: requested {requested}, only {remaining} remaining."
        )


@dataclass
class BudgetManager:
    """
    Token-budget gatekeeper that operates on a :class:`SharedContext`.

    Derives total usage from the ``token_count`` fields recorded in each
    :class:`AgentOutput` stored in ``context.agent_outputs``.  Violations
    are appended to ``context.budget_violations`` for audit.

    Usage::

        manager = BudgetManager(max_tokens=4000)
        manager.check_budget(context, agent_id="researcher", estimated_tokens=200)
        # … make LLM call …
        manager.record_usage(context, agent_id="researcher",
                             prompt_tokens=180, completion_tokens=120)
    """

    max_tokens: int = 4000
    # Minimum tokens that must remain before a call is allowed.
    reserve_tokens: int = 50
    _fallback_triggered: bool = field(default=False, init=False, repr=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _total_tokens_used(self, context: SharedContext) -> int:
        """Sum ``token_count`` across all agent outputs in the context."""
        return sum(ao.token_count for ao in context.agent_outputs.values())

    # ── Public API ────────────────────────────────────────────────────────────

    def estimate_tokens(self, text: str) -> int:
        """
        Rough token estimate based on character count.

        Uses a 4 chars-per-token heuristic — sufficient for budget gating
        before the real API count is available.
        """
        if not text:
            return 0
        return max(1, int(len(text) / _CHARS_PER_TOKEN))

    def check_budget(
        self,
        context: SharedContext,
        agent_id: str,
        estimated_tokens: int,
    ) -> None:
        """
        Assert the context has enough headroom for *estimated_tokens* more.

        Raises :class:`BudgetExceededError` if the call would exceed the budget.
        A human-readable message is also appended to ``context.budget_violations``.
        """
        tokens_used = self._total_tokens_used(context)
        effective_limit = self.max_tokens - self.reserve_tokens
        available = effective_limit - tokens_used
        if estimated_tokens > available:
            violation = (
                f"agent={agent_id} job={context.job_id}: "
                f"requested {estimated_tokens}, only {available} remaining "
                f"(budget={self.max_tokens}, used={tokens_used})"
            )
            context.budget_violations.append(violation)
            logger.warning("Budget check failed — %s", violation)
            raise BudgetExceededError(
                requested=estimated_tokens, remaining=available
            )

        logger.debug(
            "Budget OK for agent=%s: requested=%d available=%d",
            agent_id,
            estimated_tokens,
            available,
        )

    def record_usage(
        self,
        context: SharedContext,
        agent_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> int:
        """
        Update the ``token_count`` on the agent's output entry.

        If *agent_id* already has an :class:`AgentOutput` in the context,
        its ``token_count`` is incremented.  Returns the new job-wide total.
        """
        total = prompt_tokens + completion_tokens
        if agent_id in context.agent_outputs:
            context.agent_outputs[agent_id].token_count += total

        new_total = self._total_tokens_used(context)
        logger.info(
            "Tokens used — agent=%s job=%s prompt=%d completion=%d total_so_far=%d/%d",
            agent_id,
            context.job_id,
            prompt_tokens,
            completion_tokens,
            new_total,
            self.max_tokens,
        )
        return new_total

    def should_use_fallback(
        self, context: SharedContext, threshold: float = 0.9
    ) -> bool:
        """
        Return *True* when token usage exceeds *threshold* fraction of the budget.

        Callers can use this to swap to the cheaper/smaller fallback model
        before hitting the hard limit.
        """
        tokens_used = self._total_tokens_used(context)
        ratio = tokens_used / max(self.max_tokens, 1)
        if ratio >= threshold:
            if not self._fallback_triggered:
                logger.warning(
                    "Fallback threshold reached (%.0f%%) for job=%s",
                    ratio * 100,
                    context.job_id,
                )
                self._fallback_triggered = True
            return True
        return False

    def usage_summary(self, context: SharedContext) -> dict:
        """Return a JSON-serialisable summary of the current budget state."""
        tokens_used = self._total_tokens_used(context)
        return {
            "job_id": context.job_id,
            "max_tokens": self.max_tokens,
            "tokens_used": tokens_used,
            "tokens_remaining": max(0, self.max_tokens - tokens_used),
            "utilisation_pct": round(
                tokens_used / max(self.max_tokens, 1) * 100, 2
            ),
            "fallback_triggered": self._fallback_triggered,
            "violation_count": len(context.budget_violations),
        }
