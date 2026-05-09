"""
Tests for ContextBudgetManager.

Run with:
    pytest tests/test_budget_manager.py -v
"""

import pytest

from app.core.budget_manager import BudgetViolationError, ContextBudgetManager


class TestCheckBudgetUnderLimit:
    """1. check_budget returns True when under limit."""

    def test_returns_true_when_under_limit(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        assert mgr.check_budget("agent-a", tokens_to_add=500) is True

    def test_returns_true_at_exact_limit(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        assert mgr.check_budget("agent-a", tokens_to_add=1000) is True


class TestCheckBudgetExceedsLimit:
    """2. check_budget returns False when would exceed."""

    def test_returns_false_when_over_limit(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        assert mgr.check_budget("agent-a", tokens_to_add=1001) is False

    def test_returns_false_after_partial_usage(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        mgr.add_tokens("agent-a", 800)
        assert mgr.check_budget("agent-a", tokens_to_add=300) is False


class TestAddTokensRaisesOnOverflow:
    """3. add_tokens raises BudgetViolationError on overflow."""

    def test_raises_budget_violation_error(self):
        mgr = ContextBudgetManager(max_tokens=500)
        with pytest.raises(BudgetViolationError) as exc_info:
            mgr.add_tokens("agent-x", 600)
        assert exc_info.value.agent_id == "agent-x"
        assert exc_info.value.overflow == 100

    def test_does_not_mutate_used_on_overflow(self):
        mgr = ContextBudgetManager(max_tokens=500)
        try:
            mgr.add_tokens("agent-x", 600)
        except BudgetViolationError:
            pass
        assert mgr.used == 0


class TestFlagViolation:
    """4. flag_violation appends to violations list."""

    def test_appends_violation_dict(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        mgr.flag_violation("agent-z", overflow=42)
        assert len(mgr.violations) == 1
        v = mgr.violations[0]
        assert v["agent_id"] == "agent-z"
        assert v["overflow"] == 42
        assert v["max_tokens"] == 1000

    def test_multiple_violations_accumulate(self):
        mgr = ContextBudgetManager(max_tokens=1000)
        mgr.flag_violation("a", overflow=10)
        mgr.flag_violation("b", overflow=20)
        assert len(mgr.violations) == 2


class TestGetSummary:
    """5. get_summary returns correct structure."""

    def test_returns_expected_keys(self):
        mgr = ContextBudgetManager(max_tokens=2000)
        mgr.add_tokens("agent-1", 300)
        mgr.add_tokens("agent-2", 200)
        summary = mgr.get_summary()

        assert summary["max"] == 2000
        assert summary["used"] == 500
        assert summary["remaining"] == 1500
        assert summary["by_agent"] == {"agent-1": 300, "agent-2": 200}

    def test_empty_manager_summary(self):
        mgr = ContextBudgetManager(max_tokens=100)
        summary = mgr.get_summary()
        assert summary == {
            "max": 100,
            "used": 0,
            "remaining": 100,
            "by_agent": {},
        }
