"""
MetaAgent — self-optimiser that analyses eval failures and proposes prompt rewrites.

Workflow:
  1. Load an EvalRun from DB
  2. Find the worst-performing dimension across all cases
  3. Identify which agent's system_prompt most likely caused failures
  4. Call LLM (OpenRouter) to propose a rewrite with unified diff + justification
  5. Store as PromptRewrite DB row with status="pending"
  6. Return the PromptRewrite schema (NOT auto-applied)
"""

from __future__ import annotations

import difflib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.core.llm import chat
from app.database import AsyncSessionLocal
from app.eval.harness import EvalHarness
from app.models.eval_run import EvalRun
from app.models.prompt_rewrite import PromptRewrite as PromptRewriteModel
from app.schemas.eval import PromptRewrite as PromptRewriteSchema

logger = logging.getLogger(__name__)

# ── Agent → module mapping for prompt lookup ─────────────────────────────────

_AGENT_PROMPT_MAP: dict[str, str] = {
    "decomposition": "app.agents.decomposition",
    "rag": "app.agents.rag",
    "critique": "app.agents.critique",
    "synthesis": "app.agents.synthesis",
    "compression": "app.agents.compression",
}

# Dimension → most likely responsible agent
_DIMENSION_AGENT_MAP: dict[str, str] = {
    "answer_correctness": "synthesis",
    "citation_accuracy": "rag",
    "contradiction_resolution": "synthesis",
    "tool_efficiency": "decomposition",
    "budget_compliance": "compression",
    "critique_agreement": "critique",
}


def _get_agent_instance(agent_id: str):
    """Dynamically import and return an agent instance."""
    from app.agents.compression import CompressionAgent
    from app.agents.critique import CritiqueAgent
    from app.agents.decomposition import DecompositionAgent
    from app.agents.rag import RAGAgent
    from app.agents.synthesis import SynthesisAgent

    agents = {
        "decomposition": DecompositionAgent,
        "rag": RAGAgent,
        "critique": CritiqueAgent,
        "synthesis": SynthesisAgent,
        "compression": CompressionAgent,
    }
    cls = agents.get(agent_id)
    if cls is None:
        raise ValueError(f"Unknown agent: {agent_id}")
    return cls()


class MetaAgent:
    """Analyses eval failures and proposes prompt rewrites."""

    async def analyze_failures(self, run_id: str) -> PromptRewriteSchema | None:
        """
        Analyse a completed eval run, find the worst dimension, and propose
        a prompt rewrite for the responsible agent.

        Returns None if all scores are above threshold (0.7).
        """
        # 1. Load EvalRun from DB
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvalRun).where(EvalRun.id == uuid.UUID(run_id))
            )
            eval_run = result.scalar_one_or_none()

        if not eval_run or not eval_run.scores:
            logger.warning("EvalRun %s not found or has no scores.", run_id)
            return None

        # 2. Find worst-performing dimension across all cases
        dimensions = [
            "answer_correctness", "citation_accuracy",
            "contradiction_resolution", "tool_efficiency",
            "budget_compliance", "critique_agreement",
        ]

        dim_averages: dict[str, float] = {}
        for dim in dimensions:
            scores = [
                entry.get(dim, {}).get("score", 0.0)
                for entry in eval_run.scores
            ]
            dim_averages[dim] = sum(scores) / len(scores) if scores else 0.0

        worst_dim = min(dim_averages, key=dim_averages.get)  # type: ignore[arg-type]
        worst_score = dim_averages[worst_dim]

        # If everything is above threshold, no rewrite needed
        if worst_score >= 0.7:
            logger.info(
                "All dimensions above 0.7 in run %s (worst: %s=%.2f). No rewrite needed.",
                run_id, worst_dim, worst_score,
            )
            return None

        # 3. Identify which agent's system_prompt most likely caused failures
        target_agent_id = _DIMENSION_AGENT_MAP.get(worst_dim, "synthesis")
        agent_instance = _get_agent_instance(target_agent_id)
        old_prompt = agent_instance.system_prompt

        # Gather failing case details for context
        failing_cases: list[dict] = []
        for i, entry in enumerate(eval_run.scores):
            dim_score = entry.get(worst_dim, {}).get("score", 0.0)
            if dim_score < 0.6:
                case_data = eval_run.test_cases[i] if eval_run.test_cases and i < len(eval_run.test_cases) else {}
                failing_cases.append({
                    "case_id": entry.get("case_id"),
                    "case_type": entry.get("case_type"),
                    "dim_score": dim_score,
                    "justification": entry.get(worst_dim, {}).get("justification", ""),
                    "query": case_data.get("case", {}).get("query", ""),
                    "final_output": case_data.get("final_output", "")[:500],
                })

        # 4. Call LLM to propose a rewrite
        new_prompt = await self._generate_rewrite(
            agent_id=target_agent_id,
            old_prompt=old_prompt,
            worst_dim=worst_dim,
            worst_score=worst_score,
            failing_cases=failing_cases,
        )

        if not new_prompt or new_prompt.strip() == old_prompt.strip():
            logger.info("LLM returned no meaningful rewrite. Skipping.")
            return None

        # 5. Generate unified diff
        diff = "\n".join(
            difflib.unified_diff(
                old_prompt.splitlines(),
                new_prompt.splitlines(),
                fromfile=f"{target_agent_id}/old_prompt",
                tofile=f"{target_agent_id}/new_prompt",
                lineterm="",
            )
        )

        justification = (
            f"Worst dimension: {worst_dim} (avg score: {worst_score:.2f}). "
            f"{len(failing_cases)} case(s) scored below 0.6 on this dimension."
        )

        # 6. Store in DB
        rewrite_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            db_rewrite = PromptRewriteModel(
                id=uuid.UUID(rewrite_id),
                target_agent=target_agent_id,
                target_dimension=worst_dim,
                old_prompt=old_prompt,
                new_prompt=new_prompt,
                diff=diff,
                justification=justification,
                status="pending",
            )
            session.add(db_rewrite)
            await session.commit()

        logger.info(
            "Prompt rewrite %s proposed for agent=%s dim=%s.",
            rewrite_id, target_agent_id, worst_dim,
        )

        return PromptRewriteSchema(
            id=rewrite_id,
            target_agent=target_agent_id,
            target_dimension=worst_dim,
            old_prompt=old_prompt,
            new_prompt=new_prompt,
            diff=diff,
            justification=justification,
            status="pending",
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _generate_rewrite(
        self,
        agent_id: str,
        old_prompt: str,
        worst_dim: str,
        worst_score: float,
        failing_cases: list[dict],
    ) -> str:
        """Use OpenRouter LLM to generate an improved system prompt."""
        cases_text = "\n".join(
            f"  - Case {c['case_id']} ({c['case_type']}): "
            f"score={c['dim_score']}, "
            f"justification=\"{c['justification']}\", "
            f"query=\"{c['query'][:100]}\""
            for c in failing_cases[:8]  # Cap to avoid token explosion
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a prompt engineering specialist. You analyse failing "
                    "evaluation results and rewrite system prompts to improve them. "
                    "Return ONLY the improved system prompt text — no explanations, "
                    "no markdown fences, no preamble."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"The '{agent_id}' agent scored poorly on the '{worst_dim}' "
                    f"dimension (average: {worst_score:.2f}).\n\n"
                    f"Current system prompt:\n```\n{old_prompt}\n```\n\n"
                    f"Failing cases:\n{cases_text}\n\n"
                    f"Rewrite the system prompt to improve performance on "
                    f"'{worst_dim}'. Preserve the JSON output format requirement. "
                    f"Be specific and targeted in your changes."
                ),
            },
        ]

        content, _ = await chat(messages=messages, temperature=0.4)
        return content.strip()
