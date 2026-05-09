"""
EvalHarness — runs test cases through the full pipeline and scores them.

Stores results as EvalRun rows in Postgres with full JSONB payloads.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, select

from app.core.budget_manager import ContextBudgetManager
from app.core.orchestrator import run_pipeline
from app.database import AsyncSessionLocal
from app.eval.scorer import (
    score_answer_correctness,
    score_budget_compliance,
    score_citation_accuracy,
    score_contradiction_resolution,
    score_critique_agreement,
    score_tool_efficiency,
)
from app.eval.test_cases import TEST_CASES, get_cases_by_ids
from app.models.eval_run import EvalRun, RunType
from app.schemas.eval import EvalScore, ScoredDimension

logger = logging.getLogger(__name__)


class EvalHarness:
    """Orchestrates evaluation runs across all test cases."""

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_all(self, run_type: str = "full", case_ids: list[str] | None = None) -> str:
        """
        Run evaluation cases. Returns run_id.

        Parameters
        ----------
        run_type : str
            "full" (all 15 cases) or "targeted" (subset via case_ids).
        case_ids : list[str] | None
            If provided, only run these case IDs.
        """
        if case_ids:
            cases = get_cases_by_ids(case_ids)
            effective_type = RunType.TARGETED
        else:
            cases = TEST_CASES
            effective_type = RunType(run_type) if run_type in ("full", "targeted") else RunType.FULL

        run_id = str(uuid.uuid4())
        all_scores: list[dict] = []
        all_case_data: list[dict] = []

        for case in cases:
            logger.info("Eval case %s: %s", case["id"], case["query"][:60])
            try:
                score, case_data = await self._run_single_case(case, run_id)
                all_scores.append(score.model_dump())
                all_case_data.append(case_data)
            except Exception as exc:
                logger.error("Case %s failed: %s", case["id"], exc, exc_info=True)
                # Record a zero-score entry on failure
                zero = self._zero_score(case)
                all_scores.append(zero.model_dump())
                all_case_data.append({
                    "case": case,
                    "error": str(exc),
                    "agent_outputs": {},
                    "tool_calls": [],
                })

        # Fetch previous run for delta computation
        previous_run_id, delta = await self._compute_delta(all_scores)

        # Persist
        async with AsyncSessionLocal() as session:
            eval_run = EvalRun(
                id=uuid.UUID(run_id),
                run_type=effective_type,
                test_cases=all_case_data,
                scores=all_scores,
                previous_run_id=previous_run_id,
                delta=delta,
            )
            session.add(eval_run)
            await session.commit()

        logger.info("Eval run %s complete — %d cases scored.", run_id, len(all_scores))
        return run_id

    async def run_failed(self, previous_run_id: str) -> str:
        """
        Re-run only cases that scored below 0.6 total in a previous run.
        Uses the currently active (potentially approved) prompts.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvalRun).where(EvalRun.id == uuid.UUID(previous_run_id))
            )
            prev_run = result.scalar_one_or_none()
            if not prev_run or not prev_run.scores:
                raise ValueError(f"Previous run {previous_run_id} not found or has no scores.")

        # Find case_ids that scored below 0.6
        failed_ids: list[str] = []
        for score_entry in prev_run.scores:
            total = self._compute_total(score_entry)
            if total < 0.6:
                failed_ids.append(score_entry["case_id"])

        if not failed_ids:
            logger.info("No failed cases in run %s — nothing to re-run.", previous_run_id)
            return await self.run_all(run_type="targeted", case_ids=[])

        logger.info("Re-running %d failed cases: %s", len(failed_ids), failed_ids)
        return await self.run_all(run_type="targeted", case_ids=failed_ids)

    async def get_latest_summary(self) -> dict:
        """
        Return latest run grouped by category + dimension with delta vs previous.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvalRun).order_by(desc(EvalRun.timestamp)).limit(1)
            )
            latest = result.scalar_one_or_none()

        if not latest or not latest.scores:
            return {"error": "No eval runs found."}

        # Group by case type
        by_type: dict[str, list[dict]] = {}
        for entry in latest.scores:
            ct = entry.get("case_type", "unknown")
            by_type.setdefault(ct, []).append(entry)

        # Compute per-type, per-dimension averages
        summary: dict = {
            "run_id": str(latest.id),
            "timestamp": latest.timestamp.isoformat() if latest.timestamp else None,
            "case_count": len(latest.scores),
            "by_category": {},
            "delta": latest.delta,
        }

        dimensions = [
            "answer_correctness", "citation_accuracy",
            "contradiction_resolution", "tool_efficiency",
            "budget_compliance", "critique_agreement",
        ]

        for case_type, entries in by_type.items():
            cat_summary: dict[str, float] = {}
            for dim in dimensions:
                dim_scores = [
                    e.get(dim, {}).get("score", 0.0) for e in entries
                ]
                cat_summary[dim] = round(
                    sum(dim_scores) / len(dim_scores), 3
                ) if dim_scores else 0.0
            cat_summary["average_total"] = round(
                sum(cat_summary.values()) / len(dimensions), 3
            )
            summary["by_category"][case_type] = cat_summary

        return summary

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run_single_case(
        self, case: dict, run_id: str
    ) -> tuple[EvalScore, dict]:
        """Run the pipeline for one case and score all 6 dimensions."""
        job_id = f"eval-{run_id}-{case['id']}"
        budget_manager = ContextBudgetManager(max_tokens=4000)

        # Run the full pipeline (no SSE streaming for eval)
        ctx = await run_pipeline(
            query=case["query"],
            job_id=job_id,
            max_budget=4000,
            event_queue=None,
        )

        # Get the final output (synthesis content, or last agent output)
        final_output = ""
        if "synthesis" in ctx.agent_outputs:
            final_output = ctx.agent_outputs["synthesis"].content
        elif ctx.agent_outputs:
            last_key = list(ctx.agent_outputs.keys())[-1]
            final_output = ctx.agent_outputs[last_key].content

        # Get retrieved chunks from RAG agent (if available)
        from app.agents.rag import RAGAgent
        retrieved_chunks = RAGAgent._retrieved_chunks or []

        # Score all 6 dimensions
        d1 = await score_answer_correctness(final_output, case)
        d2 = await score_citation_accuracy(ctx.agent_outputs, retrieved_chunks)
        d3 = await score_contradiction_resolution(ctx)
        d4 = await score_tool_efficiency(ctx.tool_calls, case)
        d5 = await score_budget_compliance(ctx, budget_manager)
        d6 = await score_critique_agreement(ctx)

        eval_score = EvalScore(
            case_id=case["id"],
            case_type=case["type"],
            answer_correctness=d1,
            citation_accuracy=d2,
            contradiction_resolution=d3,
            tool_efficiency=d4,
            budget_compliance=d5,
            critique_agreement=d6,
        )

        case_data = {
            "case": case,
            "final_output": final_output,
            "agent_outputs": {
                k: v.model_dump() for k, v in ctx.agent_outputs.items()
            },
            "tool_calls": ctx.tool_calls,
            "contradictions": [c.model_dump() for c in ctx.contradictions],
            "budget_violations": ctx.budget_violations,
        }

        return eval_score, case_data

    def _zero_score(self, case: dict) -> EvalScore:
        """Return a zero-score EvalScore for a failed case."""
        zero = ScoredDimension(score=0.0, justification="Case execution failed.")
        return EvalScore(
            case_id=case["id"],
            case_type=case["type"],
            answer_correctness=zero,
            citation_accuracy=zero,
            contradiction_resolution=zero,
            tool_efficiency=zero,
            budget_compliance=zero,
            critique_agreement=zero,
        )

    @staticmethod
    def _compute_total(score_entry: dict) -> float:
        """Compute unweighted mean of all 6 dimensions from a dict."""
        dims = [
            "answer_correctness", "citation_accuracy",
            "contradiction_resolution", "tool_efficiency",
            "budget_compliance", "critique_agreement",
        ]
        values = [score_entry.get(d, {}).get("score", 0.0) for d in dims]
        return sum(values) / len(values) if values else 0.0

    async def _compute_delta(
        self, current_scores: list[dict]
    ) -> tuple[uuid.UUID | None, dict | None]:
        """
        Load the most recent previous run and compute score deltas.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvalRun).order_by(desc(EvalRun.timestamp)).limit(1)
            )
            prev = result.scalar_one_or_none()

        if not prev or not prev.scores:
            return None, None

        # Build previous scores lookup
        prev_lookup: dict[str, dict] = {
            s["case_id"]: s for s in prev.scores
        }

        dimensions = [
            "answer_correctness", "citation_accuracy",
            "contradiction_resolution", "tool_efficiency",
            "budget_compliance", "critique_agreement",
        ]

        delta: dict[str, dict] = {}
        for cur in current_scores:
            case_id = cur.get("case_id", "")
            prev_entry = prev_lookup.get(case_id)
            if not prev_entry:
                continue

            case_delta: dict[str, float] = {}
            for dim in dimensions:
                cur_score = cur.get(dim, {}).get("score", 0.0)
                prev_score = prev_entry.get(dim, {}).get("score", 0.0)
                case_delta[dim] = round(cur_score - prev_score, 3)

            case_delta["total"] = round(
                self._compute_total(cur) - self._compute_total(prev_entry), 3
            )
            delta[case_id] = case_delta

        return prev.id, delta
