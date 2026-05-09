"""
ContextBudgetManager — token-budget enforcement for multi-agent LLM calls.

Tracks per-agent token usage against a global maximum, raises on overflow,
and logs all violations for audit.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BudgetViolationError(Exception):
    """Raised when adding tokens would exceed the global token budget."""

    def __init__(self, agent_id: str, overflow: int) -> None:
        self.agent_id = agent_id
        self.overflow = overflow
        super().__init__(
            f"Budget violation by agent '{agent_id}': {overflow} tokens over limit."
        )


class ContextBudgetManager:
    """
    Global token-budget gatekeeper.

    Maintains a running tally of tokens used across all agents and enforces
    a hard ceiling.  Violations are recorded but never silently swallowed.

    Usage::

        mgr = ContextBudgetManager(max_tokens=4000)
        if mgr.check_budget("researcher", 500):
            mgr.add_tokens("researcher", 500)
    """

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens: int = max_tokens
        self.used: int = 0
        self.agent_usage: dict[str, int] = {}
        self.violations: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def check_budget(self, agent_id: str, tokens_to_add: int) -> bool:
        """
        Returns True if safe to add *tokens_to_add*.
        Returns False if it would exceed the budget — does NOT raise.
        """
        would_use = self.used + tokens_to_add
        safe = would_use <= self.max_tokens
        if not safe:
            logger.warning(
                "Budget check FAILED for agent=%s: would_use=%d > max=%d",
                agent_id,
                would_use,
                self.max_tokens,
            )
        return safe

    def add_tokens(self, agent_id: str, count: int) -> None:
        """
        Adds *count* tokens to the running total.
        Raises :class:`BudgetViolationError` if the addition exceeds the limit.
        NEVER silently truncates.
        """
        would_use = self.used + count
        if would_use > self.max_tokens:
            overflow = would_use - self.max_tokens
            self.flag_violation(agent_id, overflow)
            raise BudgetViolationError(agent_id=agent_id, overflow=overflow)

        self.used += count
        self.agent_usage[agent_id] = self.agent_usage.get(agent_id, 0) + count
        logger.debug(
            "Tokens added — agent=%s count=%d total=%d/%d",
            agent_id,
            count,
            self.used,
            self.max_tokens,
        )

    def remaining(self) -> int:
        """Return the number of tokens still available."""
        return self.max_tokens - self.used

    def flag_violation(self, agent_id: str, overflow: int) -> None:
        """
        Logs a violation to ``self.violations``.
        Caller must handle the violation — this method never swallows it.
        """
        violation = {
            "agent_id": agent_id,
            "overflow": overflow,
            "used": self.used,
            "max_tokens": self.max_tokens,
        }
        self.violations.append(violation)
        logger.warning("Budget violation flagged: %s", violation)

    def get_summary(self) -> dict:
        """Return a JSON-serialisable summary of the current budget state."""
        return {
            "max": self.max_tokens,
            "used": self.used,
            "remaining": self.remaining(),
            "by_agent": dict(self.agent_usage),
        }
