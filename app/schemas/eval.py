"""Schemas for evaluation scoring and prompt-rewrite tracking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ScoredDimension(BaseModel):
    """A single evaluation dimension with a normalised score and rationale."""

    score: float  # 0.0 to 1.0
    justification: str


class EvalScore(BaseModel):
    """
    Multi-dimensional evaluation result for a single test case.

    Six orthogonal dimensions are scored independently; the ``total``
    property returns the unweighted mean.
    """

    case_id: str
    case_type: Literal["baseline", "ambiguous", "adversarial"]
    answer_correctness: ScoredDimension
    citation_accuracy: ScoredDimension
    contradiction_resolution: ScoredDimension
    tool_efficiency: ScoredDimension
    budget_compliance: ScoredDimension
    critique_agreement: ScoredDimension

    @property
    def total(self) -> float:
        dims = [
            self.answer_correctness,
            self.citation_accuracy,
            self.contradiction_resolution,
            self.tool_efficiency,
            self.budget_compliance,
            self.critique_agreement,
        ]
        return sum(d.score for d in dims) / len(dims)


class PromptRewrite(BaseModel):
    """Tracks a proposed prompt mutation produced by the self-optimiser."""

    id: str
    target_agent: str
    target_dimension: str
    old_prompt: str
    new_prompt: str
    diff: str
    justification: str
    status: Literal["pending", "approved", "rejected"] = "pending"
