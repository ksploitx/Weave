"""Schemas for the shared orchestration context passed between agents."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SubTask(BaseModel):
    """A decomposed unit of work within a job."""

    id: str
    description: str
    task_type: str
    dependencies: list[str] = []
    status: Literal["pending", "running", "done", "blocked"] = "pending"
    output: str | None = None


class Citation(BaseModel):
    """Links a textual claim back to the source chunks that support it."""

    claim: str
    chunk_ids: list[str]
    agent_id: str


class FlaggedSpan(BaseModel):
    """A span of text flagged by a critic agent for revision."""

    span: str  # exact text from another agent's output
    reason: str
    suggested: str
    confidence: float


class Contradiction(BaseModel):
    """Records a detected contradiction between two agent outputs."""

    agent_a: str
    agent_b: str
    claim_a: str
    claim_b: str
    conflict_description: str
    resolved: bool = False
    resolution: str | None = None


class RoutingDecision(BaseModel):
    """An entry in the routing log that records why a job was sent to an agent."""

    from_agent: str | None
    to_agent: str
    justification: str
    timestamp: datetime


class AgentOutput(BaseModel):
    """The structured output produced by a single agent turn."""

    agent_id: str
    content: str
    confidence: float = 1.0
    citations: list[Citation] = []
    flagged_spans: list[FlaggedSpan] = []
    token_count: int = 0
    latency_ms: float = 0.0


class SharedContext(BaseModel):
    """
    The single source of truth for a running job.

    Every agent reads from and writes to this context so the orchestrator
    can track provenance, budget, contradictions, and routing decisions.
    """

    job_id: str
    query: str
    sub_tasks: list[SubTask] = []
    agent_outputs: dict[str, AgentOutput] = {}
    tool_calls: list[dict] = []
    contradictions: list[Contradiction] = []
    provenance_map: dict[str, str] = {}
    budget_violations: list[str] = []
    routing_log: list[RoutingDecision] = []
